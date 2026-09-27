/**
 * emphasis.ts — the recession easing state machine, lifted out of the WebGL-owning closure.
 *
 * WHY IT LIVES HERE. Recession (how far a device or a cable retreats when something else is the
 * subject) is the one animation whose FINAL value is visible in a screenshot. Everything else in
 * the loop either returns to a fixed value or is not part of a settled frame. Acceptance F6 asks
 * for byte-identical captures, which means the value the GPU ends up holding must be a function of
 * the TARGET alone — never of how many frames the easing happened to get, or of what `dt` the
 * scheduler handed each one.
 *
 * That property is a pure state machine over three arrays. It needs no WebGL context, so it does
 * not belong inside one: `createScene` throws without a GPU, which is why the render loop had zero
 * executed coverage and why the defect below survived a green suite.
 *
 * THE DEFECT THIS FILE WAS EXTRACTED TO FIX. The previous version snapped a value to its target
 * once it was inside the epsilon but did NOT mark the frame as moving, so on the LAST frame of an
 * easing — the frame where every remaining device snaps at once — the flush to the buffer
 * attribute was skipped entirely. The CPU array held the target; the GPU held `cur + (tgt-cur)*k`
 * from the previous frame. `converged()` then reported true and the capture harness photographed a
 * frame-timing-dependent residual: 22 of 32 PNGs differed between two runs of `review/capture.mjs`.
 * `animateFades` in scene.ts documents exactly this hazard and handles it correctly; this half did
 * not. Measured after the fix: four independent loads of `?d=core1&s=fabric` produce one canvas
 * hash, where before they produced two.
 *
 * A second instance of the same shape: the cable pass used to sit INSIDE `if (deviceMoved)`, so a
 * cable whose easing outlasted the devices' (a longer distance to travel under the same rate) was
 * abandoned mid-ease. Both passes now advance on their own terms.
 *
 * `emphasis.test.ts` steps this machine with deliberately different `dt` sequences and asserts the
 * uploaded attribute values are bit-identical. That test fails against the old behaviour.
 */
import type { InstancedBufferAttribute } from "three";

/**
 * Resolver passes between two on-screen device labels leaving — shared by the scene's resolver
 * (scene.ts recomputeLabels) and the DOM label layer (FabricLabels.tsx). Counted in FRAMES, not
 * read off a clock, so the pacing is a pure function of the frame sequence (acceptance F6 /
 * determinism.test.ts): at 60 Hz, five collisions resolved by one wheel tick leave over ~0.25 s,
 * lowest priority first, instead of vanishing together in one frame.
 */
export const LABEL_DROP_EVERY_FRAMES = 3;

/* ── THE EASE OWNER ─────────────────────────────────────────────────────────────────────────────
 *
 * Every JavaScript-stepped fade on the fabric — recession (dim/undim), the hover rim, the selection
 * halo, and (since C5 2026-09-26) the quality-tier cross-fade's overlay — is one of the
 * finite-duration eases below, and nothing outside this file steps
 * an ease of its own (`src/core/motion-inventory.test.ts` parses `src/` and fails on any
 * exponential step anywhere else, and on one here).
 *
 * WHY FINITE. These used to be EXPONENTIAL: `k = min(1, dt / RECEDE_MS); cur += (tgt - cur) * k`,
 * snapping inside an epsilon. The "_MS" constant was then a time CONSTANT, not a duration: MEASURED
 * (independent refuter, C6, 2026-09-22) the recession reached 50 % at 167 ms, 99 % at 1,067 ms and
 * settled at 1,350 ms (72.6 % done at 300 ms); the hover settled at ~417 ms and the halo at ~917 ms
 * — against the 240 / 80 / 140 ms that design-brief §4.8 promised. An ease here has an explicit
 * START (the frame its target changes), an explicit DURATION and an explicit CURVE, and it lands
 * EXACTLY on its target on the first frame at or after start + duration. So the stated duration is
 * the duration, and the settled value is the target itself — never a function of how many frames
 * the ease happened to get (acceptance F6).
 *
 * REDUCED MOTION: every ease snaps to its target on the frame its target changes (§4.8's contract:
 * the end state is identical, only the movement is removed).
 *
 * AND BOUNDED PER FRAME (C5, 2026-09-26). A finite ease advanced by the frame delta is still a
 * wall-clock ease: a frame of dt ms covers dt / duration of the curve whatever the frame rate, so ONE
 * long frame is a cut. MEASURED (acceptance grading at 7f67013): the quality-tier cross-fade — then a
 * CSS transition — fell from opacity 1 to 0.64 across one 116.6 ms host frame (bar 0.25), and the
 * same arithmetic here carried the hover rim 80 % of its ease in one 64 ms frame and the ease-out
 * selection rim 0.56 of its span on an ordinary 60 Hz frame. So every fade this owner steps advances
 * its eased FRACTION by at most FADE_MAX_STEP per frame (`capFraction`): after a stall it moves the
 * cap and then catches up with the wall-clock curve, so the fade spans at least 1 / FADE_MAX_STEP
 * frames and a slow frame delays it instead of cutting it. The cap never makes an ease end early and
 * never changes its settled value: the fraction still reaches exactly 1, on the first frame at or
 * after `durationMs` whenever the cap is not binding there (it does not bind on the last frames of
 * any ease here at 60 Hz, so §4.8's settle times are unchanged). Under reduced motion the cap does not
 * apply: the contract there is a swap, not an animation.
 */

/**
 * The most any fade the owner steps may advance in ONE frame, as a fraction of its span (|to - from|).
 * An opacity fading over [0, 1] therefore moves at most 0.2 of opacity per frame. The grading bar was
 * 0.25 per frame. Since C5 (owner decision, 2026-09-26) review/capture-motion.mjs holds all 24 tier
 * fades to this cap, 0.2. It states that number itself and does not read it from here, because the
 * verifier does not take the product's word for its bar. At 60 Hz the cap never binds on the tier
 * fade's ease-in-out (largest ordinary step 0.103). A frame of about 33 ms or more on the steep part of
 * the curve does bind it (see TIER_FADE_MS).
 */
export const FADE_MAX_STEP = 0.2;

/**
 * The eased fraction after one more frame: the wall-clock curve's value at `elapsedMs`, but never more
 * than FADE_MAX_STEP past the fraction the previous frame showed. Every curve here is monotone, so the
 * result never goes backwards. Exactly 1 once the curve has reached 1 and the cap allows it.
 */
function capFraction(prev: number, spec: EaseSpec, elapsedMs: number, reduced: boolean): number {
  if (reduced) return 1;
  const onCurve = elapsedMs >= spec.durationMs ? 1 : easeFraction(spec.curve, elapsedMs / spec.durationMs);
  return Math.min(onCurve, prev + FADE_MAX_STEP);
}

/** An ease's curve. `ease-out` is tokens.css `--ease-out`, cubic-bezier(0.16, 1, 0.3, 1);
 *  `ease-in-out` is CSS's keyword, cubic-bezier(0.42, 0, 0.58, 1). */
export type EaseCurve = "linear" | "ease-out" | "ease-in-out";

export interface EaseSpec {
  /** The constant's name, as design-brief §4.8 names it on the ease's own row. */
  readonly name: string;
  /** Total duration: the value is exactly the target at `elapsed >= durationMs`. */
  readonly durationMs: number;
  readonly curve: EaseCurve;
}

/** Recession eased over this window so the user can see WHICH nodes left the set. */
export const RECEDE_MS = 240;
/** The hover rim: must feel like a cursor property, not a transition (tokens `--dur-instant`). */
export const HOVER_MS = 80;
/** The selection rim + halo: acknowledgement of a click (tokens `--dur-fast`). */
export const SELECT_MS = 140;

export const RECEDE_EASE: EaseSpec = { name: "RECEDE_MS", durationMs: RECEDE_MS, curve: "ease-out" };
export const HOVER_EASE: EaseSpec = { name: "HOVER_MS", durationMs: HOVER_MS, curve: "linear" };
export const SELECT_EASE: EaseSpec = { name: "SELECT_MS", durationMs: SELECT_MS, curve: "ease-out" };
/** The emphasis eases: the ones `stepEaseChannel` / `stepEmphasis` step towards a changing target.
 *  The tier cross-fade's ease (below) is a one-shot the driver runs, so it is not in this list. The
 *  motion inventory does not read this list to decide what to check: it steps EVERY EaseSpec this
 *  file exports against its §4.8 row, cross-checked against this file's source. */
export const EASES: readonly EaseSpec[] = [RECEDE_EASE, HOVER_EASE, SELECT_EASE];

/* ── The quality-tier cross-fade ────────────────────────────────────────────────────────────────
 *
 * scene.ts lays the OLD tier's last frame over the canvas when the tier changes and fades it out once
 * the new tier's frames are ordinary (the hold: `createTierFadeHold`, ./stepdown). The fade used to be
 * a CSS transition (`opacity 280ms ease-in-out`), and a CSS transition runs on the wall clock: the
 * 2026-09-26 grading at 7f67013 measured opacity 1 -> 0.64 across one 116.6 ms host frame. It is now
 * stepped here, by the render loop, once per frame, on the same curve and duration, with the
 * FADE_MAX_STEP cap — so no frame, including the one after a stall or a returning tab, moves it more
 * than 0.2. The scene removes the overlay on the frame the value reaches exactly 0.
 *
 * 280 ms, not 300 (acceptance C6, 2026-09-22): the 300 ms fade MEASURED 299.9-300.1 ms — at the
 * ceiling, not under it — and the end state is first on screen up to one 60 Hz frame after the
 * duration: 280 + 16.7 < 300. At 60 Hz this ease lands on the 17th frame (283.3 ms).
 *
 * WHEN THE CAP WINS OVER 300 ms. On ordinary 60 Hz frames the cap never binds. It binds on any frame
 * of about 33 ms or more that lands on the steep part of the curve, so a single dropped frame can
 * engage it. Once engaged, the fade trails the curve and ends later than 280 ms. MEASURED by an
 * independent run on a contended host (2026-09-26): one 83.3 ms frame near the tail took a fade to
 * 316.6 ms, and one 133.4 ms frame mid-fade took another to 316.7 ms. MODELLED, with 60 Hz frames and
 * one long frame, as the harness measures a fade:
 *   - an 83-100 ms frame adds at most one 60 Hz frame over the uncapped wall-clock fade;
 *   - a 116-133 ms frame adds at most two;
 *   - a 200-250 ms frame adds at most four.
 * The wall-clock fade itself, the old CSS transition included, already reaches 300 ms when one 50 ms
 * frame lands among its last frames. So "under 300 ms" is a property of the product on ordinary
 * frames, and a stall delays the fade. The cap wins there: a cut is what the reader sees, a late
 * fade is not. review/capture-motion.mjs judges it that way. A fade over 300 ms passes only with a
 * host stall inside it, and only if every frame from 300 ms on ends the fade or moves the full cap. */
export const TIER_FADE_MS = 280;
export const TIER_FADE_EASE: EaseSpec = { name: "TIER_FADE_MS", durationMs: TIER_FADE_MS, curve: "ease-in-out" };

/** A tier cross-fade, already STARTED: its value (the overlay's opacity) is 1 and it eases to 0 over
 *  TIER_FADE_EASE from the next `stepTierFade`. */
export function createTierFade(): EaseChannel {
  const fade = createEaseChannel(1);
  stepEaseChannel(fade, TIER_FADE_EASE, 0, 0);
  return fade;
}

/**
 * Advance a tier cross-fade by one frame of `rawMs` — the frame's REAL duration, not the render
 * loop's 64 ms simulation clamp: the curve is the wall clock's, and the cap is the per-frame bound.
 * Returns true while the fade is still moving; `fade.value` is exactly 0 on the frame it ends.
 */
export function stepTierFade(fade: EaseChannel, rawMs: number, reduced = false): boolean {
  return stepEaseChannel(fade, TIER_FADE_EASE, 0, Number.isFinite(rawMs) ? rawMs : 0, reduced);
}

/** What the scene lends the tier-fade driver: the overlay and a timer. No DOM or WebGL in here. */
export interface TierFadeHost {
  /** Show the overlay at this opacity (0 < opacity < 1). */
  write(opacity: number): void;
  /** Remove the overlay. The driver calls it at most once. */
  finish(): void;
  /** The no-frames watchdog's window, ms. */
  watchdogMs: number;
  setTimer(fn: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
}

export interface TierFadeDriver {
  /** One animation frame of `rawMs`, the frame's REAL duration. Returns true while the overlay is up. */
  frame(rawMs: number, reduced: boolean): boolean;
  /** Stop without calling `finish` (the scene removed the overlay itself). Idempotent. */
  dispose(): void;
  /** The overlay's opacity now (exactly 0 once the fade has ended). */
  readonly value: number;
}

/**
 * A STARTED tier cross-fade, as the scene runs it (C5, 2026-09-26). The scene calls `frame` once per
 * animation frame, unconditionally. The driver steps the fade on `rawMs` (stepTierFade, capped at
 * FADE_MAX_STEP per frame) and writes the overlay's opacity. It removes the overlay (`finish`) on the
 * frame the value reaches exactly 0, never while it is above 0.
 *
 * THE WATCHDOG is a no-frames backstop, not a duration timer. It acts only where no frames come at
 * all: rAF suspended in a hidden tab or a throttled frame. There the overlay would otherwise cover the
 * fabric until frames resume, and since nothing is presented, removing it is not a visible cut. It
 * needs TWO consecutive `watchdogMs` windows with no stepped frame. A single main-thread stall longer
 * than the window can let the timer run before the rAF that is already due, and one strike would then
 * remove a half-faded overlay in front of the reader.
 *
 * Executed with fake timers in emphasis.test.ts. scene.test.ts pins that `frame()` drives it on `raw`.
 */
export function createTierFadeDriver(host: TierFadeHost): TierFadeDriver {
  const fade = createTierFade();
  let done = false;
  let steps = 0;
  let seen = 0;
  let idleWindows = 0;
  let timer: unknown = null;
  const stop = (): void => {
    done = true;
    if (timer !== null) host.clearTimer(timer);
    timer = null;
  };
  const end = (): void => {
    if (done) return;
    stop();
    host.finish();
  };
  const watchdog = (): void => {
    timer = null;
    if (done) return;
    idleWindows = steps === seen ? idleWindows + 1 : 0;
    seen = steps;
    if (idleWindows >= 2) {
      end();
      return;
    }
    timer = host.setTimer(watchdog, host.watchdogMs);
  };
  timer = host.setTimer(watchdog, host.watchdogMs);
  return {
    frame(rawMs: number, reduced: boolean): boolean {
      if (done) return false;
      stepTierFade(fade, rawMs, reduced);
      steps += 1;
      if (fade.value === 0) {
        end();
        return false;
      }
      host.write(fade.value);
      return true;
    },
    dispose(): void {
      if (!done) stop();
    },
    get value(): number {
      return fade.value;
    },
  };
}

/** cubic-bezier(x1, y1, x2, y2) at time fraction `x`, solved by bisection (monotone in x). */
function cubicBezier(x1: number, y1: number, x2: number, y2: number, x: number): number {
  const bx = (t: number): number => 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t * t * t;
  const by = (t: number): number => 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t;
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 40; i += 1) {
    const mid = (lo + hi) / 2;
    if (bx(mid) < x) lo = mid;
    else hi = mid;
  }
  return by((lo + hi) / 2);
}

/** The eased fraction (0..1) at time fraction `t` (0..1). Exactly 0 at 0 and exactly 1 at 1. */
export function easeFraction(curve: EaseCurve, t: number): number {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  if (curve === "linear") return t;
  return curve === "ease-in-out" ? cubicBezier(0.42, 0, 0.58, 1, t) : cubicBezier(0.16, 1, 0.3, 1, t);
}

/** One scalar eased channel (the hover rim's opacity, the halo's). */
export interface EaseChannel {
  value: number;
  from: number;
  to: number;
  elapsedMs: number;
  /** The eased fraction (0..1) of the current ease the value shows — what FADE_MAX_STEP caps. */
  fraction: number;
}

export function createEaseChannel(value = 0): EaseChannel {
  return { value, from: value, to: value, elapsedMs: 0, fraction: 1 };
}

/**
 * Advance a channel one frame towards `target`. A changed target STARTS a new ease from wherever
 * the channel is now (so an interrupted fade never jumps). Returns true while the ease is running
 * (the value changed, or has not yet reached `to`), false once it rests on its target.
 *
 * determinism: `ch.elapsedMs` accumulates the render loop's frame delta, which comes from the rAF
 * clock, so a MID-ease value does depend on this machine's frame timing. What is drawn in a SETTLED
 * frame does not: the channel holds `to` itself (not a value near it) once its capped fraction reaches
 * 1 — at once under reduced motion — and this returns true on every frame before that, which
 * keeps the scene dirty, so `converged()` (the settle the F6 captures wait on) cannot be reached
 * while any channel is mid-ease. An interrupted ease restarts from a timing-dependent value but
 * still ends on its target. The settled value is therefore a function of the target alone — pinned
 * by `emphasis.test.ts` ("an ease channel's settled value does not depend on this machine's frame
 * timing": steady, jittery and coarse dt sequences land bit-identically).
 *
 * per-frame bound: the fraction advances by at most FADE_MAX_STEP per call (`capFraction`), so one long
 * `dt` moves the value at most 0.2 of |to - from|; the value is `to` itself once the fraction is 1.
 */
export function stepEaseChannel(ch: EaseChannel, spec: EaseSpec, target: number, dt: number, reduced = false): boolean {
  if (target !== ch.to) {
    ch.from = ch.value;
    ch.to = target;
    ch.elapsedMs = 0;
    ch.fraction = 0;
  }
  if (ch.value === ch.to) return false;
  ch.elapsedMs += Math.max(0, dt);
  ch.fraction = capFraction(ch.fraction, spec, ch.elapsedMs, reduced);
  const next = ch.fraction >= 1 ? ch.to : ch.from + (ch.to - ch.from) * ch.fraction;
  const moved = next !== ch.value;
  ch.value = next;
  /* Still easing counts as motion even on a frame whose value happened not to change (a flat
     stretch of the curve at float precision): the caller keeps rendering until the ease ENDS. */
  return moved || ch.value !== ch.to;
}

/** How far a node recedes when something else is the subject. Never to zero: context survives. */
export const RECEDE_DEPTH = 0.62;
export const RECEDE_NEIGHBOUR = 0.3;

/* The structural minimum this machine needs from the scene graph. Written as its own interfaces
   rather than importing FabricGraph so the module has no dependency on the WebGL half; FabricGraph
   satisfies them structurally, and a test can satisfy them with three buffer attributes and a
   handful of plain objects. */

export interface RecedeGroup {
  recede: InstancedBufferAttribute | null;
  ghostRecede: InstancedBufferAttribute | null;
}

export interface RecedeSlot {
  /** Global index, into the current/target arrays. */
  index: number;
  /** Index into the solid or ghost instance array of the slot's group. */
  slot: number;
  ghost: boolean;
  group: RecedeGroup;
}

export interface RecedeBatch {
  /** Link id for every segment, parallel to the attribute's instance array. */
  segmentLinkIds: readonly string[];
  recede: InstancedBufferAttribute;
}

/**
 * A per-device instanced mesh built OUTSIDE the chassis groups — the state rings and the role
 * glyphs — whose instance i belongs to device `deviceIndex[i]`. Their materials are emphasis-patched
 * like the chassis, but the rings and glyphs never carried the recession attribute, so the patch read
 * zero and they stayed at full strength while their chassis desaturated (C5 audit: with one device
 * selected the brightest things on screen were the NON-selected green rings). Registering them here
 * makes them recede from the same clock and the same per-device value as the chassis they sit on.
 */
export interface RecedeMirror {
  attr: InstancedBufferAttribute;
  deviceIndex: readonly number[];
}

export interface EmphasisScene {
  order: readonly RecedeSlot[];
  groups: { values(): Iterable<RecedeGroup> };
  cables: { batches: readonly RecedeBatch[] };
  mirrors?: readonly RecedeMirror[];
}

export interface EmphasisState {
  /** Per-device recession as currently uploaded. */
  current: Float32Array;
  /** Per-device recession being eased towards. */
  target: Float32Array;
  /** Per-link recession target; a link absent from the map recedes to 0. */
  linkTarget: Map<string, number>;
  /** Force one flush of both passes — set after a rebuild or a target change. */
  dirty: boolean;
  /**
   * True once a whole cable pass changed nothing. Cables carry no CPU-side mirror array, so this
   * is what keeps an idle loop from re-scanning every segment of every batch on every rAF tick.
   * Any target change clears it; `stepEmphasis` sets it again when the pass comes up empty.
   */
  cablesSettled: boolean;
  /**
   * The RECEDE_EASE bookkeeping per device: where its current ease started (`from`), towards what
   * (`to` — NaN until a first target is seen, so a state whose `current` was written from outside
   * starts its ease from that value) and how long ago (`elapsed`, ms). A `target` that differs from
   * `to` starts a new ease from `current` on the next step.
   */
  from: Float32Array;
  to: Float32Array;
  elapsed: Float64Array;
  /** The eased fraction each device's value shows — what FADE_MAX_STEP caps per frame. */
  fraction: Float64Array;
  /** The same per cable segment, keyed by batch (allocated once per batch, never per frame). */
  segments: WeakMap<RecedeBatch, { from: Float32Array; to: Float32Array; elapsed: Float64Array; fraction: Float64Array }>;
}

export function createEmphasisState(deviceCount: number): EmphasisState {
  return {
    current: new Float32Array(deviceCount),
    target: new Float32Array(deviceCount),
    linkTarget: new Map<string, number>(),
    dirty: true,
    cablesSettled: false,
    from: new Float32Array(deviceCount),
    to: new Float32Array(deviceCount).fill(Number.NaN),
    elapsed: new Float64Array(deviceCount),
    fraction: new Float64Array(deviceCount),
    segments: new WeakMap(),
  };
}

/** Call after writing `target` or `linkTarget`: both passes must run again, and flush. */
export function markEmphasisDirty(state: EmphasisState): void {
  state.dirty = true;
  state.cablesSettled = false;
}

/**
 * Advance one frame by `dt` ms along RECEDE_EASE. Returns true when anything moved — the caller
 * uses that to keep rendering. Under `reduced` motion every value lands on its target at once.
 *
 * determinism: `state.elapsed` and each segment's `elapsed` accumulate the rAF frame delta, exactly
 * as `stepEaseChannel`'s `elapsedMs` does (see the note there), and the same argument holds: the
 * last frame of every ease writes the target itself and reports motion, so the uploaded values a
 * settled frame draws are the targets alone (`emphasis.test.ts`: three dt sequences, bit-identical).
 *
 * Allocates nothing per frame: `frame()` runs on every rAF tick and a per-frame allocation there
 * is a garbage-collection pause in the middle of an interaction. (A cable batch's bookkeeping is
 * allocated the first time the batch is seen, once.)
 */
export function stepEmphasis(scene: EmphasisScene, state: EmphasisState, dt: number, reduced = false): boolean {
  const force = state.dirty;
  state.dirty = false;
  const step = Math.max(0, dt);

  let devicesMoved = false;
  for (const s of scene.order) {
    const i = s.index;
    const cur = state.current[i] ?? 0;
    const tgt = state.target[i] ?? 0;
    if (!Object.is(state.to[i], tgt)) {
      // A new target STARTS a new ease, from wherever the value is now.
      state.from[i] = cur;
      state.to[i] = tgt;
      state.elapsed[i] = 0;
      state.fraction[i] = 0;
    }
    if (cur === tgt) continue;
    const elapsed = (state.elapsed[i] ?? 0) + step;
    state.elapsed[i] = elapsed;
    /* The last frame of an ease writes the TARGET itself and reports motion, which is what flushes
       it to the attribute below (the F6 defect was a snap that was not flushed). The fraction is
       capped per frame (FADE_MAX_STEP), so a long frame recedes a device by at most 0.2 of its span. */
    const f = capFraction(state.fraction[i] ?? 0, RECEDE_EASE, elapsed, reduced);
    state.fraction[i] = f;
    const from = state.from[i] ?? cur;
    state.current[i] = f >= 1 ? tgt : from + (tgt - from) * f;
    devicesMoved = true;
  }

  if (devicesMoved || force) {
    for (const s of scene.order) {
      const attr = s.ghost ? s.group.ghostRecede : s.group.recede;
      if (attr === null) continue;
      attr.setX(s.slot, state.current[s.index] ?? 0);
    }
    for (const group of scene.groups.values()) {
      if (group.recede !== null) group.recede.needsUpdate = true;
      if (group.ghostRecede !== null) group.ghostRecede.needsUpdate = true;
    }
    for (const mirror of scene.mirrors ?? []) {
      for (let i = 0; i < mirror.deviceIndex.length; i += 1) {
        mirror.attr.setX(i, state.current[mirror.deviceIndex[i] ?? -1] ?? 0);
      }
      mirror.attr.needsUpdate = true;
    }
  }

  /* Cables follow the same easing from the same clock, so a dim and an undim on either side of a
     selection change stay in step — but on their OWN termination, not the devices'. */
  let cablesMoved = false;
  if (!state.cablesSettled || force) {
    for (const batch of scene.cables.batches) {
      const attr = batch.recede;
      let track = state.segments.get(batch);
      if (track === undefined) {
        const n = batch.segmentLinkIds.length;
        track = { from: new Float32Array(n), to: new Float32Array(n).fill(Number.NaN), elapsed: new Float64Array(n), fraction: new Float64Array(n) };
        state.segments.set(batch, track);
      }
      let changed = false;
      for (let i = 0; i < batch.segmentLinkIds.length; i += 1) {
        const id = batch.segmentLinkIds[i];
        if (id === undefined) continue;
        /* fround, because the comparison below decides TERMINATION and the two sides must live in
           the same precision. `linkTarget` holds doubles; the attribute is a Float32Array, so
           `getX` returns the rounded value. Without this, a snapped segment reads back as
           0.6200000047683716 against a target of 0.62, counts as changed on every single frame,
           and the loop never settles — which `converged()` would then never report. (The device
           pass is safe for free: its target lives in a Float32Array too.) */
        const tgt = Math.fround(state.linkTarget.get(id) ?? 0);
        const cur = attr.getX(i);
        if (!Object.is(track.to[i], tgt)) {
          track.from[i] = cur;
          track.to[i] = tgt;
          track.elapsed[i] = 0;
          track.fraction[i] = 0;
        }
        if (cur === tgt) continue;
        const elapsed = (track.elapsed[i] ?? 0) + step;
        track.elapsed[i] = elapsed;
        const f = capFraction(track.fraction[i] ?? 0, RECEDE_EASE, elapsed, reduced);
        track.fraction[i] = f;
        const from = track.from[i] ?? cur;
        const next = f >= 1 ? tgt : from + (tgt - from) * f;
        attr.setX(i, next);
        /* Motion until the ease ENDS, even across a frame whose float32 value did not change. */
        changed = true;
      }
      if (changed || force) attr.needsUpdate = true;
      if (changed) cablesMoved = true;
    }
    state.cablesSettled = !cablesMoved;
  }

  return devicesMoved || cablesMoved;
}

/**
 * The convergence rule, as a value rather than as a closure over the renderer.
 *
 * `converged()` in scene.ts is the single predicate the whole F6 capture protocol waits on, and it
 * could not be executed by a test because it lived inside a closure that needs a GPU. It is a
 * statement about four booleans; those four are what this takes.
 */
export interface ConvergenceInputs {
  /** Shaders are compiled — before that, the first rendered frame is not the settled one. */
  compiled: boolean;
  /** A state change is still waiting to be rendered. */
  dirty: boolean;
  /** Frames rendered since the last change. */
  stillFrames: number;
  /** The camera is mid-tween. */
  cameraTweening: boolean;
}

/** At least this many still frames must follow the last change before a frame counts as final. */
export const STILL_FRAMES_FOR_CONVERGENCE = 2;

export function isConverged(x: ConvergenceInputs): boolean {
  return (
    x.compiled &&
    !x.dirty &&
    x.stillFrames >= STILL_FRAMES_FOR_CONVERGENCE &&
    !x.cameraTweening
  );
}
