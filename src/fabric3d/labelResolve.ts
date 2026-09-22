/**
 * labelResolve.ts — the scene-side label collision resolver, as a pure function.
 *
 * WHY THIS IS ITS OWN MODULE (acceptance F6, independent critic 2026-09-22). Two runs of the same
 * frozen build photographed different label sets: `access8`'s name was present on 7 of 10 fresh
 * loads of the 06-path-blocked state and absent on 3, although both runs met every settle
 * condition. Nothing read a clock or a random number, so determinism.test.ts could not see it. The
 * cause was PATH-DEPENDENT STATE: the resolver's hysteresis reads last frame's verdict, the temporal
 * half holds a newly-clear label back one frame, and the staggered drops let an overlapping label
 * keep its box for a few frames. All three are right while the camera MOVES — they are what stops
 * names flickering — and all three made the SETTLED label set a function of the frames that led to
 * it, rather than of the final camera and scene.
 *
 * So the resolver has two modes:
 *   - `settled: false` (the camera or the scene is still changing): hysteresis, the one-frame
 *     temporal hold and the staggered drops all apply, exactly as before.
 *   - `settled: true` (the scene has rendered its final frame and is idle): ONE history-free pass.
 *     No margin either way, no hold, no stagger, and "already on screen" is not a priority term, so
 *     the verdict is a pure function of the projected boxes, the priority classes and the depths.
 *
 * It lives outside scene.ts's closure because a resolver inside a closure that needs a GPU cannot
 * be executed by a test; `labelResolve.test.ts` runs it from two different histories onto the same
 * final boxes and asserts the same kept set.
 */

/** Placement class below this is an investigation subject (selection, hover, alarm, trace, highlight). */
export const URGENT_CLASS_BELOW = 10;

export interface LabelResolverState {
  /** Last pass's verdict per label: the hysteresis memory. Updated in place. */
  wasKept: Uint8Array;
  /** 1 when a hidden label found its box clear last pass (the temporal hold). Updated in place. */
  pending: Uint8Array;
  /** Resolver passes since an on-screen label last left (the staggered drops). */
  passesSinceDrop: number;
  /**
   * Passes since each label last changed verdict — the TIME-DOMAIN hysteresis (see
   * `LABEL_MIN_DWELL_PASSES`). Optional so a caller that does not keep it gets the old behaviour;
   * updated in place when present.
   */
  age?: Uint16Array;
}

/**
 * The minimum number of moving-camera passes a label keeps a verdict before it may reverse it.
 *
 * The spatial margin (`hysteresisPx`) and the one-frame temporal hold both work on ONE frame's
 * geometry, so neither stops a name leaving and coming back a few frames later while two boxes
 * slide past each other. MEASURED (C5 audit, 2026-09-22, slow 60-step orbit, real GPU):
 * `labelsShown` changed 24 times in 60 samples with single-sample blips (22 -> 21 -> 22), and
 * reproduced here at 19 reversals within six frames over one orbit. So a label that has just
 * appeared stays at least this many passes, and one that has just left stays gone as long, while
 * the camera moves; a settled pass ignores it (it is history). Twelve passes is ~200 ms at 60 Hz —
 * long enough that a reversal reads as a decision, short enough not to lag a deliberate move.
 * Subjects of the investigation (urgent classes) are exempt: they show at once and stay.
 *
 * The dwell alone halved it (14 -> 7 per-label reversals within 30 frames over the same orbit) but
 * could not remove the trades: as two boxes slide past each other, one name leaves and another
 * takes its place, and the count reads 22 -> 21 -> 22 with no single label reversing. So while the
 * camera MOVES, names only leave (`cameraMoving`); names that have become clear appear on the first
 * still frame, where the reader can actually read them. The count is then monotone within a
 * gesture, and every appearance lands at rest.
 */
export const LABEL_MIN_DWELL_PASSES = 12;

export interface LabelResolverInput {
  /** Screen boxes, 4 per label (x0, y0, x1, y1); NaN in x0 = anchor not visible. */
  boxes: Float32Array;
  /** Priority class per label; lower is placed first. */
  classOf: ArrayLike<number>;
  /** Camera distance per label, the tie-break within a class (nearer first). */
  distance: ArrayLike<number>;
  /** Margin (px) a shown label must overlap by before it goes, and a hidden one clear by to return. */
  hysteresisPx: number;
  /** Passes between two on-screen labels leaving. */
  dropEveryPasses: number;
  /** A label whose box is behind a nearer chassis is not placed (not applied to urgent classes). */
  behindNearerChassis?: (i: number, x0: number, y0: number, x1: number, y1: number) => boolean;
  /** The scene is idle and this is its final frame: resolve without any history. */
  settled: boolean;
  /**
   * The camera moved this frame. While it does, a hidden label does not APPEAR (it waits, pending,
   * for the first still frame); a shown label still leaves when its box is taken, staggered and
   * after its dwell. See LABEL_MIN_DWELL_PASSES for the measurement.
   */
  cameraMoving?: boolean;
}

export interface LabelResolverResult {
  /** 1 = the label is placed. Length = number of labels. */
  kept: Uint8Array;
  shown: number;
  behind: number;
  /** A held or pending label needs another pass to reach its verdict. Always false when settled. */
  needsFrame: boolean;
}

export function resolveLabels(input: LabelResolverInput, state: LabelResolverState): LabelResolverResult {
  const { boxes, classOf, distance, settled } = input;
  const n = state.wasKept.length;
  const kept = new Uint8Array(n);
  const key = new Float64Array(n);
  const rank: number[] = [];
  for (let i = 0; i < n; i += 1) {
    rank.push(i);
    /* Within a class, a label already on screen outranks one that is not — the ORDERING half of
       the hysteresis. It is history, so the settled pass leaves it out. */
    const seen = settled ? 0 : state.wasKept[i] === 1 ? 0 : 5e6;
    key[i] = (classOf[i] ?? 0) * 1e7 + seen + Math.min(999999, Math.round(distance[i] ?? 0));
  }
  // Index as the final tie-break: Array.prototype.sort is stable, and `rank` starts in index order.
  rank.sort((a, b) => (key[a] ?? 0) - (key[b] ?? 0));

  let shown = 0;
  let behind = 0;
  let pendingAny = false;
  const age = state.age !== undefined && state.age.length === n ? state.age : null;
  for (const i of rank) {
    if (Number.isNaN(boxes[i * 4] ?? NaN)) {
      state.pending[i] = 0;
      continue;
    }
    const m = settled ? 0 : state.wasKept[i] === 1 ? input.hysteresisPx : -input.hysteresisPx;
    const x0 = (boxes[i * 4] ?? 0) + m;
    const y0 = (boxes[i * 4 + 1] ?? 0) + m;
    const x1 = (boxes[i * 4 + 2] ?? 0) - m;
    const y1 = (boxes[i * 4 + 3] ?? 0) - m;
    let clear = true;
    for (let k = 0; k < n && clear; k += 1) {
      if (kept[k] !== 1) continue;
      const bx0 = boxes[k * 4] ?? 0;
      const by0 = boxes[k * 4 + 1] ?? 0;
      const bx1 = boxes[k * 4 + 2] ?? 0;
      const by1 = boxes[k * 4 + 3] ?? 0;
      if (x0 < bx1 && x1 > bx0 && y0 < by1 && y1 > by0) clear = false;
    }
    const urgent = (classOf[i] ?? 0) < URGENT_CLASS_BELOW;
    if (clear && !urgent && input.behindNearerChassis?.(i, x0, y0, x1, y1) === true) {
      clear = false;
      behind += 1;
    }
    if (settled) {
      /* The final frame: a clear box is placed now. The temporal hold exists to stop a name
         flashing into a gap for one frame of a MOVING camera; a still camera has no next frame. */
      state.pending[i] = 0;
      if (urgent || clear) {
        kept[i] = 1;
        shown += 1;
      }
      continue;
    }
    /* A hidden name that has become clear does not appear while the camera moves, nor within the
       dwell of its last change (LABEL_MIN_DWELL_PASSES): it stays pending, and claims no box. */
    const heldBack =
      !urgent &&
      state.wasKept[i] === 0 &&
      (input.cameraMoving === true || (age !== null && (age[i] ?? 0) < LABEL_MIN_DWELL_PASSES));
    if (clear && heldBack) {
      state.pending[i] = 1;
      pendingAny = true;
    } else if (urgent || (clear && (state.wasKept[i] === 1 || state.pending[i] === 1))) {
      kept[i] = 1;
      state.pending[i] = 0;
      shown += 1;
    } else if (clear) {
      state.pending[i] = 1;
      pendingAny = true;
    } else {
      state.pending[i] = 0;
    }
  }

  let needsFrame = pendingAny;
  if (!settled && age !== null) {
    /* The LEAVING half of the dwell (LABEL_MIN_DWELL_PASSES): a name that appeared fewer than the
       dwell's passes ago keeps its box a little longer. Before the staggered drops, so a label held
       here is not also counted as one of their leavers. (The APPEARING half is in the placement
       loop above, so a held-back name never claims a box it will not draw.) */
    for (let i = 0; i < n; i += 1) {
      if ((age[i] ?? 0) >= LABEL_MIN_DWELL_PASSES) continue;
      if (Number.isNaN(boxes[i * 4] ?? NaN)) continue; // left the view: gone, never held
      if ((classOf[i] ?? 0) < URGENT_CLASS_BELOW) continue;
      if (state.wasKept[i] === 1 && kept[i] === 0) {
        kept[i] = 1;
        shown += 1;
        needsFrame = true;
      }
    }
  }
  if (!settled) {
    /* STAGGERED DROPS: at most one label that was on screen and still has an anchor leaves per
       `dropEveryPasses` passes, lowest priority first; the rest keep their box until their turn. */
    state.passesSinceDrop += 1;
    let dropsAllowed = state.passesSinceDrop >= input.dropEveryPasses ? 1 : 0;
    const leaving: number[] = [];
    for (let i = 0; i < n; i += 1) {
      if (state.wasKept[i] === 1 && kept[i] === 0 && !Number.isNaN(boxes[i * 4] ?? NaN)) leaving.push(i);
    }
    leaving.sort((a, b) => (key[b] ?? 0) - (key[a] ?? 0) || b - a);
    for (const i of leaving) {
      if (dropsAllowed > 0) {
        dropsAllowed -= 1;
        state.passesSinceDrop = 0;
        continue;
      }
      kept[i] = 1;
      shown += 1;
      needsFrame = true;
    }
  } else {
    /* The settled pass is a fresh start for the stagger too: the next drop after the camera moves
       again is paced from here, not from whatever the pre-settle frames happened to leave. */
    state.passesSinceDrop = input.dropEveryPasses;
  }
  if (age !== null) {
    for (let i = 0; i < n; i += 1) {
      age[i] = kept[i] !== state.wasKept[i] ? 0 : Math.min(0xffff, (age[i] ?? 0) + 1);
    }
  }
  state.wasKept.set(kept);
  return { kept, shown, behind, needsFrame };
}
