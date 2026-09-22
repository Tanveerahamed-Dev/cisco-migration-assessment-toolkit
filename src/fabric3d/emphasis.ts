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
 * Every JavaScript-stepped fade on the fabric — recession (dim/undim), the hover rim and the
 * selection halo — is one of the finite-duration eases below, and nothing outside this file steps
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
 */

/** An ease's curve. `ease-out` is tokens.css `--ease-out`, cubic-bezier(0.16, 1, 0.3, 1). */
export type EaseCurve = "linear" | "ease-out";

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
/** Every ease this owner defines. The motion inventory steps each one against its §4.8 row. */
export const EASES: readonly EaseSpec[] = [RECEDE_EASE, HOVER_EASE, SELECT_EASE];

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
  return curve === "linear" ? t : cubicBezier(0.16, 1, 0.3, 1, t);
}

/**
 * The value of one ease at `elapsedMs` after it started from `from` towards `to`. Returns `to`
 * itself — not a value near it — once `elapsedMs >= durationMs`, or at once under reduced motion.
 */
export function easeValue(spec: EaseSpec, from: number, to: number, elapsedMs: number, reduced = false): number {
  if (reduced || elapsedMs >= spec.durationMs || from === to) return to;
  return from + (to - from) * easeFraction(spec.curve, elapsedMs / spec.durationMs);
}

/** One scalar eased channel (the hover rim's opacity, the halo's). */
export interface EaseChannel {
  value: number;
  from: number;
  to: number;
  elapsedMs: number;
}

export function createEaseChannel(value = 0): EaseChannel {
  return { value, from: value, to: value, elapsedMs: 0 };
}

/**
 * Advance a channel one frame towards `target`. A changed target STARTS a new ease from wherever
 * the channel is now (so an interrupted fade never jumps). Returns true when the value changed.
 */
export function stepEaseChannel(ch: EaseChannel, spec: EaseSpec, target: number, dt: number, reduced = false): boolean {
  if (target !== ch.to) {
    ch.from = ch.value;
    ch.to = target;
    ch.elapsedMs = 0;
  }
  if (ch.value === ch.to) return false;
  ch.elapsedMs += Math.max(0, dt);
  const next = easeValue(spec, ch.from, ch.to, ch.elapsedMs, reduced);
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
  /** The same per cable segment, keyed by batch (allocated once per batch, never per frame). */
  segments: WeakMap<RecedeBatch, { from: Float32Array; to: Float32Array; elapsed: Float64Array }>;
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
    }
    if (cur === tgt) continue;
    const elapsed = (state.elapsed[i] ?? 0) + step;
    state.elapsed[i] = elapsed;
    /* The last frame of an ease writes the TARGET itself and reports motion, which is what flushes
       it to the attribute below (the F6 defect was a snap that was not flushed). */
    state.current[i] = easeValue(RECEDE_EASE, state.from[i] ?? cur, tgt, elapsed, reduced);
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
        track = { from: new Float32Array(n), to: new Float32Array(n).fill(Number.NaN), elapsed: new Float64Array(n) };
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
        }
        if (cur === tgt) continue;
        const elapsed = (track.elapsed[i] ?? 0) + step;
        track.elapsed[i] = elapsed;
        const next = easeValue(RECEDE_EASE, track.from[i] ?? cur, tgt, elapsed, reduced);
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
