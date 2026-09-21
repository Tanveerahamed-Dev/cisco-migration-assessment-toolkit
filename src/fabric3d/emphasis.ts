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

/** Recession eased over this window so the user can see WHICH nodes left the set. */
export const RECEDE_MS = 240;

/** How far a node recedes when something else is the subject. Never to zero: context survives. */
export const RECEDE_DEPTH = 0.62;
export const RECEDE_NEIGHBOUR = 0.14;

/**
 * Below this distance the value SNAPS to its target rather than easing further — and the snap is
 * flushed, which is the whole point. An exponential ease never actually arrives, so without a snap
 * the loop either never settles or settles wherever it was when someone stopped looking.
 */
export const RECEDE_EPSILON = 0.002;

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

export interface EmphasisScene {
  order: readonly RecedeSlot[];
  groups: { values(): Iterable<RecedeGroup> };
  cables: { batches: readonly RecedeBatch[] };
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
}

export function createEmphasisState(deviceCount: number): EmphasisState {
  return {
    current: new Float32Array(deviceCount),
    target: new Float32Array(deviceCount),
    linkTarget: new Map<string, number>(),
    dirty: true,
    cablesSettled: false,
  };
}

/** Call after writing `target` or `linkTarget`: both passes must run again, and flush. */
export function markEmphasisDirty(state: EmphasisState): void {
  state.dirty = true;
  state.cablesSettled = false;
}

/**
 * Advance one frame. Returns true when anything moved — the caller uses that to keep rendering.
 *
 * Allocates nothing: `frame()` runs on every rAF tick and a per-frame allocation there is a
 * garbage-collection pause in the middle of an interaction.
 */
export function stepEmphasis(scene: EmphasisScene, state: EmphasisState, dt: number): boolean {
  const k = Math.min(1, dt / RECEDE_MS);
  const force = state.dirty;
  state.dirty = false;

  let devicesMoved = false;
  for (const s of scene.order) {
    const cur = state.current[s.index] ?? 0;
    const tgt = state.target[s.index] ?? 0;
    if (Math.abs(cur - tgt) < RECEDE_EPSILON) {
      if (cur !== tgt) {
        /* Snap AND report motion. Reporting it is what flushes the snapped value to the attribute
           below; without it the GPU keeps the last eased value and the picture depends on frame
           timing. This is the F6 defect. */
        state.current[s.index] = tgt;
        devicesMoved = true;
      }
      continue;
    }
    state.current[s.index] = cur + (tgt - cur) * k;
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
  }

  /* Cables follow the same easing from the same clock, so a dim and an undim on either side of a
     selection change stay in step — but on their OWN termination, not the devices'. */
  let cablesMoved = false;
  if (!state.cablesSettled || force) {
    for (const batch of scene.cables.batches) {
      const attr = batch.recede;
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
        const next = Math.abs(cur - tgt) < RECEDE_EPSILON ? tgt : cur + (tgt - cur) * k;
        if (next !== cur) {
          attr.setX(i, next);
          changed = true;
        }
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
