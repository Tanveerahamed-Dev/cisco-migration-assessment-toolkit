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

/**
 * THE ONE DWELL GATE — every per-label show/hide decision over TIME, for both label surfaces.
 *
 * Two surfaces decide whether a name is drawn: this module's `resolveLabels` (the scene's resolver)
 * and FabricLabels.tsx's DOM declutter (the text the reader actually sees). Each used to own its
 * own rule, and they disagreed: MEASURED (C5 motion audit, 2026-09-22, the harness's six camera
 * sequences on a real GPU) the scene resolver blinked on none, while the DOM layer — which had a
 * spatial hysteresis but no time dwell, and let a hidden name reappear while the camera moved —
 * blinked on four of six (`access16 hidden 4f` in an orbit drag, `access2`/`access4` 2–4 frame runs
 * at a focus fly, `access15 hidden 1f` at a reset fly). Both now ask THIS function, so the two
 * cannot disagree about when a name may appear or leave. Each surface keeps only its own GEOMETRY
 * (what "clear" means for its boxes) and the shared stagger pacing (`dropEveryPasses`).
 *
 * The rules, in order:
 *   - settled (the final still frame): history-free — shown iff urgent or clear (acceptance F6);
 *   - urgent (an investigation subject: selected, hovered, alarmed, marked): shown at once, kept;
 *   - a shown label whose box is still clear stays;
 *   - a shown label whose box is taken stays until LABEL_MIN_DWELL_PASSES passes after it appeared
 *     (`held`); after that it LEAVES (and the caller's stagger may still pace the leaving);
 *   - a hidden label whose box is clear does NOT appear while the camera moves, nor within the
 *     dwell of its last change: it waits, `pending`, claiming no box;
 *   - otherwise it needs its box clear on two consecutive passes (the one-frame temporal hold)
 *     before it appears.
 */
export interface LabelDwellInput {
  /** The label was drawn after the previous pass. */
  wasShown: boolean;
  /** Passes since its verdict last changed; `Infinity` when the caller keeps no age. */
  age: number;
  /** It found its box clear on the previous pass while hidden (the temporal hold). */
  pending: boolean;
  /** Its box is clear this pass (the surface's own geometry says so). */
  clear: boolean;
  /** An investigation subject: exempt from every hold. */
  urgent: boolean;
  /** The camera moved this pass. */
  cameraMoving: boolean;
  /** The scene is idle and this is its final frame. */
  settled: boolean;
}

export interface LabelDwellVerdict {
  /** Draw the label this pass. */
  show: boolean;
  /** Shown only because its dwell has not run out: its box is taken, so it claims none. */
  held: boolean;
  /** Carry into the next pass as the temporal hold. */
  pending: boolean;
  /** A shown label the gate lets leave this pass; the caller's stagger may still pace it. */
  leaving: boolean;
}

/**
 * Which label is URGENT (exempt from every hold of the gate below). A MARKED label — the selection,
 * the trace's ending, a cut point, a stranded host, a finding's host — always: its mark is the
 * answer to the question on screen. The HOVERED label only while the camera is still. During an
 * orbit drag the pointer sweeps across devices without pointing at any of them, and exempting
 * each one it crosses is itself the popping: MEASURED (motion probe, high tier, orbit drag, 3 of 3
 * runs, with the dwell gate in place) access16 left under the dwell's rules and came straight back
 * 2–4 frames later because the drag's pointer crossed its chassis. On a still camera a hovered
 * name still shows at once (design brief 4.7: hover promotes the label).
 */
export const labelUrgent = (marked: boolean, hovered: boolean, cameraMoving: boolean): boolean =>
  marked || (hovered && !cameraMoving);

/**
 * THE SETTLE'S HALF OF THE DWELL. The settled pass is history-free (F6), so it has no dwell of its
 * own: whatever it disagrees with, it reverses at once. It therefore may not RUN while it would
 * reverse a label younger than the dwell — a surface keeps asking for passes (the scene resolver's
 * `needsFrame`) or reports itself still converging (the DOM layer) until every such label has held
 * its verdict LABEL_MIN_DWELL_PASSES passes. `age` is the label's age AFTER the pass just run (0 =
 * it changed on that pass), which is the age the next, settled pass would see.
 *
 * MEASURED (review/capture-motion.mjs, light/high/dolly-in, 2026-09-22): `access12 hidden for only
 * 5 frame(s)` in a move of six moving frames — the name left at the start of the move and the
 * settled pass on the first idle frame put it straight back, the move having ended before its
 * dwell did. The final set is unchanged (still the history-free one, F6); only WHEN it is reached.
 */
export const labelSettleMayReverse = (age: number): boolean => age >= LABEL_MIN_DWELL_PASSES;

export function labelDwellVerdict(g: LabelDwellInput): LabelDwellVerdict {
  if (g.settled) {
    const show = g.urgent || g.clear;
    return { show, held: false, pending: false, leaving: g.wasShown && !show };
  }
  if (g.urgent) return { show: true, held: false, pending: false, leaving: false };
  if (g.wasShown) {
    if (g.clear) return { show: true, held: false, pending: false, leaving: false };
    if (g.age < LABEL_MIN_DWELL_PASSES) return { show: true, held: true, pending: false, leaving: false };
    return { show: false, held: false, pending: false, leaving: true };
  }
  if (!g.clear) return { show: false, held: false, pending: false, leaving: false };
  if (g.cameraMoving || g.age < LABEL_MIN_DWELL_PASSES) return { show: false, held: false, pending: true, leaving: false };
  if (g.pending) return { show: true, held: false, pending: false, leaving: false };
  return { show: false, held: false, pending: true, leaving: false };
}

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
  /** A held or pending label needs another pass to reach its verdict, or the settled pass would
   *  reverse a label younger than the dwell (`labelSettleMayReverse`). Always false when settled. */
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
  const held: number[] = [];
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
    /* The verdict over TIME is the shared gate's (`labelDwellVerdict` above), never re-derived
       here: the DOM label layer asks the same function, so the two surfaces cannot disagree. The
       settled pass is history-free inside it (F6); a hidden name that has become clear does not
       appear while the camera moves nor within its dwell, and stays pending, claiming no box. */
    const v = labelDwellVerdict({
      wasShown: state.wasKept[i] === 1,
      age: age === null ? Infinity : (age[i] ?? 0),
      pending: state.pending[i] === 1,
      clear,
      urgent,
      cameraMoving: input.cameraMoving === true,
      settled,
    });
    state.pending[i] = v.pending ? 1 : 0;
    if (v.pending) pendingAny = true;
    if (v.held) held.push(i);
    else if (v.show) {
      kept[i] = 1;
      shown += 1;
    }
  }

  let needsFrame = pendingAny;
  /* The LEAVING half of the dwell: a name the gate holds (it appeared fewer than
     LABEL_MIN_DWELL_PASSES passes ago) keeps its box a little longer. Kept only after placement, so
     a leaving name never blocks one being placed, and before the staggered drops, so a label held
     here is not also counted as one of their leavers. A label that left the VIEW (NaN box) never
     reaches the gate: gone, never held. */
  for (const i of held) {
    kept[i] = 1;
    shown += 1;
    needsFrame = true;
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
  if (!settled && age !== null && !needsFrame) {
    /* The settled pass the scene would run next, on these same boxes (it runs over the frame last
       rendered), computed on scratch state so nothing here moves the real history. Where it would
       reverse a label younger than the dwell, another pass is owed: the scene keeps rendering its
       still frames — each an ordinary pass under the gate — and runs its settled pass only once
       the reversal would no longer be a blink (`labelSettleMayReverse`). Urgent labels and labels
       with no anchor are the same in both passes, so they never hold it. */
    const hf = resolveLabels(
      { ...input, settled: true, cameraMoving: false },
      { wasKept: kept.slice(), pending: new Uint8Array(n), passesSinceDrop: input.dropEveryPasses },
    ).kept;
    for (let i = 0; i < n && !needsFrame; i += 1) {
      if ((hf[i] ?? 0) !== (kept[i] ?? 0) && !labelSettleMayReverse(age[i] ?? 0)) needsFrame = true;
    }
  }
  return { kept, shown, behind, needsFrame };
}
