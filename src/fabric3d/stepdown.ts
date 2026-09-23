/**
 * Adaptive quality step-down: WHEN has the machine sustainably missed the frame budget?
 *
 * This used to be a +1/-1 counter: +1 for every rendered frame over 24 ms, -1 for every one under
 * it, step down at a net 45. That rule is structurally blind to the commonest real degradation, a
 * BIMODAL frame series. Measured 2026-09-21 in headed Chromium under sustained camera motion: a
 * p50 of 16.7 ms with a p95 of 50-83 ms, i.e. a sustained median of 29-39 fps, and the counter
 * never tripped, because every fast frame paid back a slow one. The tier stayed `high` and
 * `stats().qualityReasons` announced nothing — degradation reported as health, which acceptance E4
 * forbids.
 *
 * The rule is now judged over a sliding WINDOW of rendered frames, by two independent tests:
 *
 *  1. the FRACTION of rendered frames over `slowMs` — a bimodal series fails this even when its
 *     median is perfect, which is exactly the case the counter could not see;
 *  2. the window's effective frame rate (frames / summed frame time) below `minFps` — a uniformly
 *     slow series fails this even though no single frame looks like an outlier.
 *
 * Each frame's contribution to the summed time is capped at `frameCapMs`, so ONE catastrophic
 * hitch (a shader link, a GC) cannot on its own drag the window's fps below the bar and cost the
 * user a quality tier for the rest of the session. A hitch still counts once in the fraction.
 *
 * Pure and clock-free, so the rule is stepped by a test rather than asserted in prose.
 */

export interface StepDownOptions {
  /** A rendered frame slower than this is "over budget". */
  slowMs: number;
  /** Summed (capped) rendered-frame time a window must span before it is judged. */
  windowMs: number;
  /**
   * A window with fewer rendered frames than this is not judged — unless the window already spans
   * `windowMs`, in which case the floor is clamped to what a spanning window can hold (see
   * `spanFloor` in `createStepDownJudge`). Time is the gate; this only guards the count.
   */
  minFrames: number;
  /** Step down when at least this fraction of the window's frames are over `slowMs`. */
  overFraction: number;
  /** Step down when the window's effective rate is below this. */
  minFps: number;
  /** Per-frame cap on the time contribution, so one hitch cannot decide the window. */
  frameCapMs: number;
}

export const STEP_DOWN_DEFAULTS: StepDownOptions = {
  slowMs: 24,
  windowMs: 2000,
  minFrames: 30,
  overFraction: 0.25,
  // E4's bar is 55 fps; stepping down at 45 keeps a machine that is merely near the bar on the
  // tier it chose, and moves one that is plainly under it. "Keeps it" is not "stays silent about
  // it": the 45-55 fps band is REPORTED by `createFrameRateBar` below, never passed off as health.
  minFps: 45,
  frameCapMs: 100,
};

export interface StepDownVerdict {
  /** True when the window says the tier should step down. */
  step: boolean;
  /** The measurement, in a sentence, for `stats().qualityReasons`. Empty unless `step`. */
  reason: string;
}

export interface StepDownJudge {
  /**
   * Record one RENDERED, non-suspended frame of `rawMs`, and judge the window.
   *
   * `presentationMs` is the display's measured presentation period (see
   * `createPresentationCadence`), or null when it is not known. When the display presents slower
   * than the judge's own bars assume, the bars are rescaled to it — see `effectiveBars`.
   */
  push(rawMs: number, presentationMs?: number | null): StepDownVerdict;
  /** Forget the window (a rebuilt chain, a tier change). */
  reset(): void;
  /** Frames currently in the window — for tests. */
  size(): number;
  /**
   * The window's effective frame rate (frames / summed capped frame time), or null while the window
   * is too short to judge (it has not yet spanned `windowMs` of capped rendered-frame time).
   * Because of the cap this is an UPPER bound on the true rate when frames exceed `frameCapMs`.
   */
  windowFps(): number | null;
  /** The window's TRUE rate (frames / summed uncapped time), or null exactly when `windowFps` is. */
  windowRawFps(): number | null;
}

export function createStepDownJudge(opts: Partial<StepDownOptions> = {}): StepDownJudge {
  const o: StepDownOptions = { ...STEP_DOWN_DEFAULTS, ...opts };
  const frames: number[] = [];
  let head = 0;
  let sum = 0;
  let over = 0;
  let rawSum = 0;

  /* The frame floor for a window that spans `windowMs`. Every frame contributes at most
     `frameCapMs` to `sum`, so a spanning window holds at least windowMs / frameCapMs frames at any
     rate; the floor is clamped to that (and to an absolute minimum of 3).

     It used to be `minFrames` flat (30). Thirty frames in a 2 s window is 15 fps, so below about
     14.3 fps (70 ms frames) a spanning window could never hold 30 frames: `windowFps()` stayed null
     for good, the tier never stepped down and the E4 bar was never raised. Measured under CDP 4x
     CPU throttling at 4-12 fps, the status line still read "tier high" and `qualityReasons` still
     said "full quality" — degradation rendered as health, the one thing E4 forbids. A window that
     has spanned `windowMs` of rendered frames IS sustained evidence, however few frames it took. */
  const spanFloor = Math.max(3, Math.min(o.minFrames, Math.floor(o.windowMs / Math.max(1, o.frameCapMs))));
  function judgeable(n: number): boolean {
    return sum >= o.windowMs && n >= spanFloor && sum > 0;
  }

  function reset(): void {
    frames.length = 0;
    head = 0;
    sum = 0;
    over = 0;
    rawSum = 0;
  }

  /* The slow-frame threshold the current window was counted against. The fraction is kept as a
     running count, so a change of threshold (the display's cadence moved) recounts the window once
     rather than mixing two thresholds in one fraction. */
  let countedAt = o.slowMs;
  function recount(slowMs: number): void {
    over = 0;
    for (let i = head; i < frames.length; i += 1) if ((frames[i] ?? 0) > slowMs) over += 1;
    countedAt = slowMs;
  }

  function push(rawMs: number, presentationMs: number | null = null): StepDownVerdict {
    const bars = effectiveBars(o, presentationMs);
    if (bars.slowMs !== countedAt) recount(bars.slowMs);
    const ms = Number.isFinite(rawMs) && rawMs > 0 ? rawMs : 0;
    const capped = Math.min(o.frameCapMs, ms);
    frames.push(ms);
    sum += capped;
    rawSum += ms;
    if (ms > bars.slowMs) over += 1;
    // Slide: drop the oldest frames while the window still spans windowMs without them.
    while (frames.length - head > 1) {
      const oldest = frames[head] ?? 0;
      const oldestCapped = Math.min(o.frameCapMs, oldest);
      if (sum - oldestCapped < o.windowMs) break;
      sum -= oldestCapped;
      rawSum -= oldest;
      if (oldest > bars.slowMs) over -= 1;
      head += 1;
    }
    // Compact occasionally so the backing array does not grow without bound.
    if (head > 512) {
      frames.splice(0, head);
      head = 0;
    }
    const n = frames.length - head;
    if (!judgeable(n)) return { step: false, reason: "" };
    const fraction = over / n;
    const fps = (1000 * n) / sum;
    /* The sentence states the TRUE rate: the capped one is only the judge's hitch-resistant test
       statistic, and "10.0 fps" over a window of 500 ms frames would understate the problem 5x. */
    const trueFps = rawSum > 0 ? (1000 * n) / rawSum : fps;
    if (fraction >= o.overFraction || fps < bars.minFps) {
      const pct = Math.round(fraction * 100);
      return {
        step: true,
        reason:
          `${pct}% of the last ${n} rendered frames were over ${Math.round(bars.slowMs)} ms and the window ran at ` +
          `${trueFps.toFixed(1)} fps (step-down at >= ${Math.round(o.overFraction * 100)}% over or ` +
          `< ${Math.round(bars.minFps)} fps over ${(o.windowMs / 1000).toFixed(0)} s` +
          (bars.displayLimited && presentationMs != null
            ? `, rescaled to a display presenting at ${(1000 / presentationMs).toFixed(0)} Hz)`
            : ")"),
      };
    }
    return { step: false, reason: "" };
  }

  function windowFps(): number | null {
    const n = frames.length - head;
    if (!judgeable(n)) return null;
    return (1000 * n) / sum;
  }

  function windowRawFps(): number | null {
    const n = frames.length - head;
    if (!judgeable(n) || !(rawSum > 0)) return null;
    return (1000 * n) / rawSum;
  }

  return { push, reset, size: () => frames.length - head, windowFps, windowRawFps };
}

/* ── the display's own cadence: a frame cannot be faster than the display presents ─────────────
 *
 * MEASURED (E4 audit, 2026-09-22, laptop on battery with Windows Energy Saver on): Chromium
 * presented at 30 Hz, every rAF interval 33.3-33.5 ms whatever was drawn. The judge above read
 * that as "100% of frames over 24 ms, 30.0 fps" and stepped high -> balanced -> low — and the
 * frame rate stayed at exactly 30.0 fps with the draw calls cut from 78 to 32. No tier renders
 * faster than the display presents, so the step bought nothing and cost bloom, SSAO and the
 * outlines for the rest of the session: the "drive a refresh-limited display to low for good"
 * outcome the 45 fps rule was chosen to avoid, reached from a cap below 45 Hz.
 *
 * The cadence is measured where the renderer cannot be the cause: on IDLE frames, the rAF
 * callbacks in which the fabric drew nothing. Their interval is the browser's presentation period
 * and nothing else. A GPU that cannot keep up on a 60 Hz display still idles at 16.7 ms, so it is
 * judged exactly as before; a display (or a power governor) presenting at 30 Hz idles at 33.3 ms,
 * and the judge is told so. Only a TIGHT cluster counts — the middle half of the idle intervals
 * within `spread` of their median — so idle frames stretched by the page's own work are never
 * mistaken for a slow display.
 */
export interface PresentationCadenceOptions {
  /** Idle intervals kept. */
  samples: number;
  /** Fewer idle intervals than this: the cadence is not known. */
  minSamples: number;
  /** The interquartile range must sit within this fraction of the median. */
  spread: number;
}

export const PRESENTATION_CADENCE_DEFAULTS: PresentationCadenceOptions = { samples: 48, minSamples: 12, spread: 0.15 };

export interface PresentationCadence {
  /** Record the rAF interval of a frame in which the fabric rendered NOTHING. */
  noteIdle(intervalMs: number): void;
  /** The measured presentation period in ms, or null while unknown or not tightly clustered. */
  periodMs(): number | null;
  /** Forget (a visibility change: the display may be a different one when the page comes back). */
  reset(): void;
}

export function createPresentationCadence(opts: Partial<PresentationCadenceOptions> = {}): PresentationCadence {
  const o: PresentationCadenceOptions = { ...PRESENTATION_CADENCE_DEFAULTS, ...opts };
  const ring: number[] = [];
  let at = 0;
  let cached: number | null | undefined;
  return {
    noteIdle(intervalMs) {
      if (!(Number.isFinite(intervalMs) && intervalMs > 0 && intervalMs < 250)) return;
      if (ring.length < o.samples) ring.push(intervalMs);
      else ring[at] = intervalMs;
      at = (at + 1) % o.samples;
      cached = undefined;
    },
    periodMs() {
      if (cached !== undefined) return cached;
      if (ring.length < o.minSamples) return (cached = null);
      const sorted = [...ring].sort((a, b) => a - b);
      const q = (f: number): number => sorted[Math.min(sorted.length - 1, Math.floor(f * sorted.length))] ?? 0;
      const med = q(0.5);
      if (!(med > 0) || q(0.75) - q(0.25) > med * o.spread) return (cached = null);
      return (cached = med);
    },
    reset() {
      ring.length = 0;
      at = 0;
      cached = undefined;
    },
  };
}

/** A frame up to this many presentation periods long is on time. */
const DISPLAY_LIMIT_HEADROOM = 1.25;

/**
 * The bars a window is judged against, given the display's presentation period. A frame that
 * lasted one presentation period is on time by definition, so the slow-frame threshold is never
 * below 1.25 periods and the rate floor never above 80 % of the display's rate. At 60 Hz both
 * bars are unchanged (20.8 ms < 24 ms; 48 fps > 45 fps); at 30 Hz a frame is slow past 41.7 ms
 * and the window past 24 fps — i.e. only when the renderer misses presentations the display
 * offered.
 */
export function effectiveBars(
  o: Pick<StepDownOptions, "slowMs" | "minFps">,
  presentationMs: number | null | undefined,
): { slowMs: number; minFps: number; displayLimited: boolean } {
  if (presentationMs == null || !(presentationMs > 0)) return { slowMs: o.slowMs, minFps: o.minFps, displayLimited: false };
  const slowMs = Math.max(o.slowMs, presentationMs * DISPLAY_LIMIT_HEADROOM);
  const minFps = Math.min(o.minFps, 1000 / (presentationMs * DISPLAY_LIMIT_HEADROOM));
  return { slowMs, minFps, displayLimited: slowMs !== o.slowMs || minFps !== o.minFps };
}

/**
 * The sentence for `qualityReasons` while something other than this renderer sets the frame rate.
 *
 * It names what was MEASURED, not a cause it cannot see: idle frames arriving every N ms say the
 * display presents no faster, OR that other per-frame work on the page (another animation loop, a
 * heavy observer) holds every frame that long. Verified by injecting 45 ms of work into every
 * animation frame: the idle cadence read 50 ms. Either way no tier change can make frames arrive
 * sooner, which is the only thing the step-down rule needs to know — so the rule stands, and the
 * sentence does not claim "the display" when it may be the page.
 */
export function displayLimitReason(presentationMs: number): string {
  return (
    `frame rate capped at ${(1000 / presentationMs).toFixed(0)} Hz by something other than this ` +
    `renderer: frames arrive every ${presentationMs.toFixed(1)} ms even when the fabric draws nothing ` +
    `(a power-saving governor, a slow panel, or other per-frame work on the page); no tier renders ` +
    `faster than that, so the step-down rule judges frames against that cadence and does not trade ` +
    `quality for it`
  );
}

/* ── the E4 bar: REPORTED, whatever the tier rule decides ──────────────────────────────────────
 *
 * The step-down judge deliberately tolerates a band below E4's 55 fps bar (it steps at < 45 fps or
 * >= 25% slow frames), because a tier change is expensive and a machine near the bar should keep
 * the tier it chose. But tolerated is not the same as healthy, and that band was SILENT. Measured
 * 2026-09-22 (headed, 1920x1080, 8 s continuous orbit drag, three runs): 53.9-54.5 fps rendered,
 * p95 33.3 ms, ~11% of frames over 20 ms — and the tier stayed `high` with `qualityReasons`
 * saying only "full quality". The pure judge confirms it: uniform 20 ms (50 fps), uniform 22 ms
 * (45.5 fps) and a 20%-slow bimodal series (~50 fps) all return `step: false`.
 *
 * So the bar is tracked on its own, over the same kind of window of rendered frames, and it changes
 * nothing about rendering — it only makes the shortfall explicit: `stats().frameRateBelowBar`, a
 * sentence in `qualityReasons`, and the words on the permanent status line. It is independent of
 * the tier rule on purpose: raising the step-down threshold to the bar would drive a display that
 * is refresh-limited under 55 Hz (a 50 Hz panel, a remote-desktop session) down to `low` for good,
 * because no tier can render faster than the display presents. Reporting is correct everywhere;
 * stepping is correct only where the renderer is the limit.
 *
 * Hysteresis: the flag rises when the window runs below the bar and falls only once it is back at
 * `clearFps`, so a series sitting on the bar does not flicker the status line.
 */
export const FRAME_RATE_BAR_FPS = 55;

export interface FrameRateBarOptions {
  /** The bar. Below it, the window is reported. */
  barFps: number;
  /** A reported window clears only at or above this rate. */
  clearFps: number;
  /** Window shape, as for the step-down judge. */
  windowMs: number;
  minFrames: number;
  frameCapMs: number;
}

export const FRAME_RATE_BAR_DEFAULTS: FrameRateBarOptions = {
  barFps: FRAME_RATE_BAR_FPS,
  clearFps: FRAME_RATE_BAR_FPS + 1,
  windowMs: STEP_DOWN_DEFAULTS.windowMs,
  minFrames: STEP_DOWN_DEFAULTS.minFrames,
  frameCapMs: STEP_DOWN_DEFAULTS.frameCapMs,
};

export interface FrameRateBar {
  /** Record one RENDERED, non-suspended frame of `rawMs`. Returns whether the flag is now raised. */
  push(rawMs: number): boolean;
  /** True while the last judgeable window of rendered frames ran below the bar. */
  below(): boolean;
  /** The window rate that raised the flag, or null while it is not raised. */
  reportedFps(): number | null;
  /** The sentence for `qualityReasons`, or "" while the bar is held. */
  reason(): string;
  /** Forget the window and lower the flag (a tier change: the new tier has not been measured). */
  reset(): void;
}

export function createFrameRateBar(opts: Partial<FrameRateBarOptions> = {}): FrameRateBar {
  const o: FrameRateBarOptions = { ...FRAME_RATE_BAR_DEFAULTS, ...opts };
  /* The step-down judge's window, reused for its measurement only: its own verdict is never read. */
  const win = createStepDownJudge({
    windowMs: o.windowMs,
    minFrames: o.minFrames,
    frameCapMs: o.frameCapMs,
    minFps: 0,
    overFraction: Number.POSITIVE_INFINITY,
  });
  let flagged: number | null = null;
  return {
    push(rawMs) {
      win.push(rawMs);
      /* Judged on the capped rate (one hitch cannot raise the flag), REPORTED at the true rate:
         under the cap every frame counts 100 ms, so a 2 fps window judges as 10 fps, and saying
         "10.0 fps" to the reader would understate the shortfall. */
      const fps = win.windowFps();
      if (fps === null) return flagged !== null;
      const shown = win.windowRawFps() ?? fps;
      if (fps < o.barFps) flagged = shown;
      else if (flagged !== null && fps >= o.clearFps) flagged = null;
      else if (flagged !== null) flagged = shown;
      return flagged !== null;
    },
    below: () => flagged !== null,
    reportedFps: () => flagged,
    reason: () =>
      flagged === null
        ? ""
        : `rendering at ${flagged.toFixed(1)} fps over at least the last ${(o.windowMs / 1000).toFixed(0)} s of drawn frames, ` +
          `below the ${o.barFps} fps bar at this tier (the step-down rule tolerates this band; it does not make it healthy)`,
    reset() {
      win.reset();
      flagged = null;
    },
  };
}

/* ── recovery: the other half of the rule ──────────────────────────────────────────────────────
 *
 * Step-down alone is a ratchet: measured on a real Intel GPU (render audit, headless Chromium),
 * about fifteen wheel-dolly steps tripped it twice in a row, high -> balanced -> low, and because
 * nothing ever stepped back up the session stayed on low for good — bloom, outlines, SSAO and fine
 * geometry gone mid-use and never returned, on a machine that ran `high` at 60 fps before the
 * gesture. A burst of heavy interaction is evidence about the burst, not about the machine.
 *
 * So a stepped-down tier is RETRIED once the fabric has been idle long enough that the retry cannot
 * land in the middle of a gesture, one tier at a time, never above the tier the session chose for
 * itself. Hysteresis is a strike count, not a timer: a tier that is stepped down FROM again after a
 * retry has proved the machine cannot hold it, and after `maxRetries` such failures it is never
 * retried again this session. The worst case is therefore bounded — at most `maxRetries` pops per
 * tier per session — instead of the unbounded oscillation a naive step-up would produce.
 */

export type RecoverableTier = "high" | "balanced" | "low";
const ORDER: readonly RecoverableTier[] = ["low", "balanced", "high"];

export interface RecoveryOptions {
  /** How long the scene must have rendered nothing before a retry. */
  idleMs: number;
  /** Failed retries a tier is allowed before it becomes this session's ceiling. */
  maxRetries: number;
}

export const RECOVERY_DEFAULTS: RecoveryOptions = { idleMs: 6000, maxRetries: 1 };

export interface StepUpPolicy {
  /** The tier the session chose for itself; recovery never goes above it. */
  setCeiling(tier: RecoverableTier): void;
  /** Record an automatic step-down FROM `tier`. Counts as a strike if `tier` was a retry. */
  noteStepDown(from: RecoverableTier): void;
  /** Given the current tier and how long the scene has been idle, the tier to retry, or null. */
  poll(current: RecoverableTier, idleMs: number): RecoverableTier | null;
  /** Failed retries per tier — for tests and for the announced reason. */
  strikes(tier: RecoverableTier): number;
}

export function createStepUpPolicy(opts: Partial<RecoveryOptions> = {}): StepUpPolicy {
  const o: RecoveryOptions = { ...RECOVERY_DEFAULTS, ...opts };
  let ceiling: RecoverableTier | null = null;
  const strikeCount = new Map<RecoverableTier, number>();
  const retried = new Set<RecoverableTier>();
  return {
    setCeiling(tier) {
      ceiling = tier;
      strikeCount.clear();
      retried.clear();
    },
    noteStepDown(from) {
      if (retried.has(from)) {
        strikeCount.set(from, (strikeCount.get(from) ?? 0) + 1);
        retried.delete(from);
      }
    },
    poll(current, idleMs) {
      if (ceiling === null || idleMs < o.idleMs) return null;
      const at = ORDER.indexOf(current);
      if (at >= ORDER.indexOf(ceiling)) return null;
      const up = ORDER[at + 1];
      if (up === undefined || (strikeCount.get(up) ?? 0) >= o.maxRetries) return null;
      retried.add(up);
      return up;
    },
    strikes: (tier) => strikeCount.get(tier) ?? 0,
  };
}

/* ── attribution: was a slow frame the FABRIC's? ───────────────────────────────────────────────
 *
 * The judge above is fed the rAF-to-rAF interval, and that interval is not the fabric's cost: it
 * is the fabric's frame PLUS everything else the main thread did before the next frame — React
 * committing a selection across four surfaces, the page's own layout, a list filter recomputing.
 * MEASURED (release build, headed, Intel GPU, 2026-09-21): clicking through twelve findings with
 * the camera at rest stepped the fabric high -> balanced -> low, and clearing a 17-character
 * query stepped it high -> balanced on its own. Every one of those step-downs then REBUILT the
 * post chain and re-linked its programs, which is where the 454-541 ms FrameRequestCallback frames
 * that acceptance E4/E5 flagged came from: the page did something slow, the fabric blamed itself,
 * and the fabric's remedy was the slowest thing in the application.
 *
 * So a frame is judged only when the browser did not report FOREIGN long work inside its
 * interval. Foreign means a main-thread long task (the Long Tasks API, > 50 ms) that did not host
 * one of this loop's frame callbacks. What still counts, deliberately:
 *   - every rendering task that ran a fabric frame, whole — page layout and paint included;
 *   - a GPU that cannot keep up — that stretches the interval with no main-thread task at all;
 *   - host contention that lands on the fabric's own frames.
 * Excluded frames are still MEASURED and still published (fps, worst frame, last frame): this
 * changes what the tier rule blames, never what the telemetry reports. Where the Long Tasks API is
 * absent nothing is ever excluded, which is the previous behaviour.
 */

export interface ForeignWorkLedger {
  /** A main-thread long task the browser reported, [start, start + duration). */
  noteLongTask(start: number, duration: number): void;
  /** The timestamp `requestAnimationFrame` handed one of the fabric's frame callbacks. */
  noteFrame(at: number): void;
  /** Milliseconds of foreign long-task work overlapping the interval (from, to]. */
  foreignMs(from: number, to: number): number;
  /** Forget everything that ended before `t`. */
  prune(t: number): void;
}

/**
 * How far a rendering task may start before the rAF timestamp it hosts. The timestamp is the
 * frame's begin time, and the task that runs the callback starts at or just after it; the slack
 * only has to absorb scheduling jitter, so it is well under one frame.
 */
const FRAME_TASK_SLACK_MS = 8;

const overlap = (a0: number, a1: number, b0: number, b1: number): number =>
  Math.max(0, Math.min(a1, b1) - Math.max(a0, b0));

/**
 * A long task is the FABRIC's when it is the rendering task that ran one of its frame callbacks —
 * i.e. it contains a frame timestamp. That attribution is conservative on purpose: the same task
 * also carries the page's style, layout and paint, and all of it is counted as the fabric's, so a
 * slow rendering task can never be excused. Every OTHER long task in a frame interval — an input
 * handler, a React commit in a timer or a scheduler message, a list recompute — is foreign.
 */
export function createForeignWorkLedger(): ForeignWorkLedger {
  const tasks: { s: number; e: number }[] = [];
  const frames: number[] = [];
  const hostsFrame = (t: { s: number; e: number }): boolean =>
    frames.some((f) => f >= t.s - FRAME_TASK_SLACK_MS && f <= t.e);
  return {
    noteLongTask(start, duration) {
      if (Number.isFinite(start) && Number.isFinite(duration) && duration > 0) tasks.push({ s: start, e: start + duration });
    },
    noteFrame(at) {
      if (Number.isFinite(at)) frames.push(at);
    },
    foreignMs(from, to) {
      let total = 0;
      for (const t of tasks) {
        if (hostsFrame(t)) continue;
        total += overlap(t.s, t.e, from, to);
      }
      return total;
    },
    prune(t) {
      let keep = 0;
      for (const x of tasks) if (x.e >= t) tasks[keep++] = x;
      tasks.length = keep;
      keep = 0;
      /* A frame timestamp is kept a little longer than the tasks, so a task that straddles `t`
         can still find the frame it hosted. */
      for (const f of frames) if (f >= t - 1000) frames[keep++] = f;
      frames.length = keep;
    },
  };
}

/**
 * Is a frame over (from, to] evidence about the fabric? No when more than `share` of the interval
 * was foreign long work — then it measured the page, not the renderer.
 */
export function frameIsFabricEvidence(ledger: ForeignWorkLedger, from: number, to: number, share = 0.5): boolean {
  const span = to - from;
  if (!(span > 0)) return true;
  return ledger.foreignMs(from, to) <= span * share;
}

/* ── WHEN a tier change may land: never on an interaction's path ────────────────────────────────
 *
 * The judge above decides WHETHER the tier should change; this decides WHEN the change is allowed
 * to happen. They used to be the same moment, and a tier change is the most expensive thing the
 * fabric ever does: it rebuilds the post chain and, at a geometry-key boundary, the graph, and the
 * rebuilt chain's programs are linked at first use. MEASURED (unminified release build, headed,
 * Intel iGPU, 2026-09-21, scratch probes on the J2 "select a device in 3-D" actuation): the third
 * of fourteen canvas clicks stepped high -> balanced and the sixth balanced -> low, each linking
 * 1-22 new programs, with a 254 ms `FrameRequestCallback:frame` long animation frame landing in the
 * presentation of the NEXT click; under the E4 camera-motion condition (10 x focusDevice) the same
 * rebuild was 684 ms of `getProgramInfoLog` first-use waits inside the tween, i.e. the 266-633 ms
 * tail frames E4 cites were the remedy, not the disease. Acceptance E5's "40 x ArrowDown" frame
 * attributed to `Fabric3D FrameRequestCallback` (432.7 ms) is the same shape.
 *
 * So a verdict to step down is HELD until the page is quiet: no discrete input (a pointer press, a
 * key, a wheel notch) for `quietMs`, no pointer held down, and no camera tween in flight. The
 * verdict is not weakened — the tier still changes, and still announces why — it only stops
 * landing in the frame that presents an interaction or in the middle of a camera move.
 *
 * Bounded, so the gate can never become "never": a pointer held longer than `maxHeldMs` (a lost
 * pointerup outside the window, or a genuinely sustained orbit) stops counting as a gesture, and a
 * held verdict older than `maxHoldMs` lands regardless. A machine that is really too slow is
 * therefore still stepped down within a few seconds of sustained load, which is E4's own rule.
 *
 * Camera motion is NOT one of these bounded holds (C5 (b), 2026-09-23): the scene refuses a landing
 * while the camera moves BEFORE it asks this gate (scene.ts `landHeldStepDown`), because the rebuilt
 * chain presents nothing until its re-warm-up ends and a mid-orbit landing froze a moving view for
 * ~600 ms-1 s. `maxHoldMs` therefore overrides input quiet and a held pointer, never a moving camera.
 */

export interface GestureGateOptions {
  /** Quiet period after the last discrete input before a tier change may land. */
  quietMs: number;
  /** A pointer held longer than this no longer holds the gate (lost pointerup, sustained orbit). */
  maxHeldMs: number;
  /** A held verdict older than this lands whatever the page is doing. */
  maxHoldMs: number;
}

export const GESTURE_GATE_DEFAULTS: GestureGateOptions = { quietMs: 1200, maxHeldMs: 4000, maxHoldMs: 6000 };

export interface GestureGate {
  /** A discrete input (pointer press, key, wheel) at `at`, on the rAF/event clock. */
  noteInput(at: number): void;
  /** A pointer went down (`true`) or up/cancelled (`false`) at `at`. */
  notePointer(down: boolean, at: number): void;
  /**
   * May a tier change held since `heldSince` land at `now`? `cameraMoving` is true while the camera
   * is not at rest — a tween in flight, or any motion (a damping tail included) within the scene's
   * motion hold. A held verdict older than `maxHoldMs` always may.
   */
  mayLand(now: number, heldSince: number, cameraMoving: boolean): boolean;
}

export function createGestureGate(opts: Partial<GestureGateOptions> = {}): GestureGate {
  const o: GestureGateOptions = { ...GESTURE_GATE_DEFAULTS, ...opts };
  let lastInput = Number.NEGATIVE_INFINITY;
  let pointerDownAt: number | null = null;
  return {
    noteInput(at) {
      if (Number.isFinite(at)) lastInput = Math.max(lastInput, at);
    },
    notePointer(down, at) {
      if (!Number.isFinite(at)) return;
      lastInput = Math.max(lastInput, at);
      pointerDownAt = down ? at : null;
    },
    mayLand(now, heldSince, cameraMoving) {
      if (now - heldSince >= o.maxHoldMs) return true;
      if (cameraMoving) return false;
      if (pointerDownAt !== null && now - pointerDownAt < o.maxHeldMs) return false;
      return now - lastInput >= o.quietMs;
    },
  };
}

/* ── HOW LONG the old tier's picture may be held over the new tier's frames ─────────────────────
 *
 * A tier change lays the old tier's last frame over the canvas and fades it out once the new tier
 * has presented (scene.ts, "tier cross-fade"). The fade waits for the new tier's frames to be
 * ORDINARY ones — `calmFrames` consecutive frames under `calmFrameMs` — because a heavy frame just
 * after the swap (the new chain's first-use program links) swallowed a fade started at once
 * (measured low -> high, one 210 ms frame: opacity 0.94 -> 0.056, a cut). `maxHoldMs` bounds it.
 *
 * AND IT NEVER HOLDS A PICTURE THE FABRIC HAS LEFT (acceptance report 2026-09-23, C5 (b)). The
 * calm wait was the ONLY release besides the backstop, and a contended host never presents three
 * frames under 40 ms: an automatic step-down mid-orbit held the old tier's frame at opacity 1 for
 * ~1,000 ms while the camera kept moving underneath — 126 of 282 moving frames changed nothing on
 * screen, then a 6.08x one-frame jump. The overlay is only a faithful stand-in while the frames
 * under it show the SAME view of the SAME content, so the first frame on which the camera moved or
 * the content changed starts the fade: from then the new tier is the one presenting motion, and the
 * cross-fade is the whole transition. The calm wait now applies only to a still view, where the held
 * picture IS the current one, at the old tier, and nothing waits on it.
 */
export interface TierFadeHoldOptions {
  /** A frame interval under this is an ordinary one. */
  calmFrameMs: number;
  /** This many consecutive ordinary frames release the hold. */
  calmFrames: number;
  /** The hold never outlasts this, counted from the new tier's first presented frame. */
  maxHoldMs: number;
}

export const TIER_FADE_HOLD_DEFAULTS: TierFadeHoldOptions = { calmFrameMs: 40, calmFrames: 3, maxHoldMs: 1200 };

export interface TierFadeHold {
  /**
   * One animation frame after the new tier's first presented frame (`since`). `frameMs` is that
   * frame's interval; `viewChanged` whether the camera moved or the content changed since `since`.
   * True when the fade must start now.
   */
  frame(now: number, frameMs: number, viewChanged: boolean): boolean;
}

export function createTierFadeHold(since: number, opts: Partial<TierFadeHoldOptions> = {}): TierFadeHold {
  const o: TierFadeHoldOptions = { ...TIER_FADE_HOLD_DEFAULTS, ...opts };
  let calm = 0;
  return {
    frame(now, frameMs, viewChanged) {
      /* The picture under the overlay is no longer the one it was taken from: holding it now would
         freeze a moving camera or an animating fabric. The new tier presents the change instead. */
      if (viewChanged) return true;
      if (now - since >= o.maxHoldMs) return true;
      calm = frameMs > 0 && frameMs < o.calmFrameMs ? calm + 1 : 0;
      return calm >= o.calmFrames;
    },
  };
}
