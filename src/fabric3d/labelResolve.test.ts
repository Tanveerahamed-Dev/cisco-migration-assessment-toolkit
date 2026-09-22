/**
 * labelResolve.test.ts — the settled label set is a function of the final state, not of the path.
 *
 * Independent critic, acceptance F6 (2026-09-22): two runs of the same frozen build photographed
 * different label sets — `access8` kept on 7 of 10 fresh loads, dropped on 3 — with every settle
 * condition met both times. The scene resolver's hysteresis, one-frame temporal hold and staggered
 * drops all read the frames BEFORE the still one. These tests drive the resolver from different
 * histories onto the same final boxes and require the same verdict once `settled` is set, and show
 * that without `settled` the history really does decide (so the settled pass is not vacuous).
 */
import { describe, expect, it } from "vitest";

import { LABEL_MIN_DWELL_PASSES, resolveLabels, type LabelResolverState } from "./labelResolve";

const H = 5;
const DROP_EVERY = 3;

/** Boxes as [x0, y0, x1, y1] per label; `null` = anchor not visible. */
const boxesOf = (list: ([number, number, number, number] | null)[]): Float32Array => {
  const out = new Float32Array(list.length * 4);
  list.forEach((b, i) => {
    if (b === null) out[i * 4] = NaN;
    else out.set(b, i * 4);
  });
  return out;
};

const fresh = (n: number): LabelResolverState => ({
  wasKept: new Uint8Array(n),
  pending: new Uint8Array(n),
  passesSinceDrop: DROP_EVERY,
});

const pass = (
  state: LabelResolverState,
  boxes: Float32Array,
  settled: boolean,
  classOf: number[] = [60, 60, 60],
  distance: number[] = [10, 20, 30],
): number[] =>
  Array.from(
    resolveLabels({ boxes, classOf, distance, hysteresisPx: H, dropEveryPasses: DROP_EVERY, settled }, state).kept,
  );

/* Label 0 sits at [0,0]-[100,20]. Label 1's final box overlaps it by 3 px: inside the hysteresis
   margin, so a label that was ALREADY shown keeps it while moving and a hidden one does not earn it. */
const FINAL = boxesOf([[0, 0, 100, 20], [97, 0, 197, 20], [400, 0, 500, 20]]);
const APART = boxesOf([[0, 0, 100, 20], [300, 0, 400, 20], [400, 0, 500, 20]]);
const ON_TOP = boxesOf([[0, 0, 100, 20], [0, 0, 100, 20], [400, 0, 500, 20]]);

/** Several frames of a camera path, then the still frame(s). */
const run = (path: Float32Array[], settleWith: Float32Array, settledPasses: number): number[] => {
  const state = fresh(3);
  for (const b of path) pass(state, b, false);
  let kept: number[] = [];
  for (let i = 0; i < settledPasses; i += 1) kept = pass(state, settleWith, true);
  return kept;
};

describe("scene label resolver: the settled pass is history-free (acceptance F6)", () => {
  it("WITHOUT the settled pass the verdict on the same final boxes depends on the path", () => {
    // Guard against a vacuous test: the history really does change the moving-camera verdict.
    const fromApart = fresh(3);
    for (const b of [APART, APART, FINAL, FINAL]) pass(fromApart, b, false);
    const fromOnTop = fresh(3);
    for (const b of [ON_TOP, ON_TOP, FINAL, FINAL]) pass(fromOnTop, b, false);
    expect(Array.from(fromApart.wasKept)).not.toEqual(Array.from(fromOnTop.wasKept));
  });

  it("two different histories onto the same final boxes settle to the same kept set", () => {
    const a = run([APART, APART, APART, FINAL], FINAL, 1);
    const b = run([ON_TOP, ON_TOP, ON_TOP, FINAL], FINAL, 1);
    const c = run([], FINAL, 1);
    expect(a).toEqual(b);
    expect(a).toEqual(c);
    // And it is the geometric answer: a 3 px overlap is an overlap once no margin applies.
    expect(a).toEqual([1, 0, 1]);
  });

  it("the settled verdict is the same on every still frame, and needs no further frame", () => {
    const state = fresh(3);
    for (const b of [APART, ON_TOP, FINAL]) pass(state, b, false);
    const first = resolveLabels(
      { boxes: FINAL, classOf: [60, 60, 60], distance: [10, 20, 30], hysteresisPx: H, dropEveryPasses: DROP_EVERY, settled: true },
      state,
    );
    expect(first.needsFrame).toBe(false);
    expect(pass(state, FINAL, true)).toEqual(Array.from(first.kept));
  });

  it("no staggered drop and no temporal hold survive into the settled frame", () => {
    // Three labels shown apart, then all three land on one box in the same frame. Moving, only one
    // may leave per DROP_EVERY passes; settled, both losers leave at once.
    const apart3 = boxesOf([[0, 0, 100, 20], [300, 0, 400, 20], [600, 0, 700, 20]]);
    const pile = boxesOf([[0, 0, 100, 20], [0, 0, 100, 20], [0, 0, 100, 20]]);
    const moving = fresh(3);
    pass(moving, apart3, false);
    pass(moving, apart3, false);
    expect(pass(moving, pile, false).filter((k) => k === 1).length).toBeGreaterThan(1);

    expect(run([apart3, apart3, pile], pile, 1)).toEqual([1, 0, 0]);
    expect(run([pile], pile, 1)).toEqual([1, 0, 0]);
    // A label that just became clear appears on the settled frame, not one frame later.
    expect(run([pile, pile, apart3], apart3, 1)).toEqual([1, 1, 1]);
  });

  it("ties inside a class are broken by distance then index, never by what was on screen", () => {
    // Two labels on the same box at the same distance: the lower index wins whichever was shown.
    const same = boxesOf([[0, 0, 100, 20], [0, 0, 100, 20]]);
    const s1: LabelResolverState = { wasKept: Uint8Array.from([0, 1]), pending: new Uint8Array(2), passesSinceDrop: 0 };
    const s2: LabelResolverState = { wasKept: Uint8Array.from([1, 0]), pending: new Uint8Array(2), passesSinceDrop: 0 };
    const k1 = pass(s1, same, true, [60, 60], [5, 5]);
    const k2 = pass(s2, same, true, [60, 60], [5, 5]);
    expect(k1).toEqual([1, 0]);
    expect(k2).toEqual(k1);
  });

  it("an investigation subject is kept whatever it overlaps, settled or not", () => {
    const pile = boxesOf([[0, 0, 100, 20], [0, 0, 100, 20], [0, 0, 100, 20]]);
    expect(pass(fresh(3), pile, true, [60, 0, 60])).toEqual([0, 1, 0]);
    expect(pass(fresh(3), pile, false, [60, 0, 60])).toEqual([0, 1, 0]);
  });
});

/* ── the settled pass never reverses a change younger than the dwell (C5 residual) ───────────── */

/**
 * The scene's own loop, restated (scene.ts `frame` / `recomputeLabels`): a frame whose camera moved,
 * or whose previous pass asked for another (`needsFrame` -> `labelsNeedFrame` -> dirty), RENDERS and
 * runs a moving-camera pass over that frame's boxes; the first frame with nothing owed is idle and
 * runs ONE history-free settled pass over the boxes last rendered; later idle frames run nothing.
 * `boxesAt(f)` is what the camera projects on frame f; `movingAt(f)` whether the camera moved.
 * Returns label `j`'s visibility per frame and the frame of the settled pass.
 */
function sceneLoop(
  frames: number,
  boxesAt: (f: number) => Float32Array,
  movingAt: (f: number) => boolean,
  j: number,
  n = 2,
): { vis: boolean[]; settledAt: number; final: number[] } {
  const state: LabelResolverState = {
    wasKept: new Uint8Array(n),
    pending: new Uint8Array(n),
    passesSinceDrop: DROP_EVERY,
    age: new Uint16Array(n).fill(0xffff),
  };
  const vis: boolean[] = [];
  let owed = true;
  let settledAt = -1;
  let final: number[] = [];
  let lastBoxes = boxesAt(0);
  for (let f = 0; f < frames; f += 1) {
    const moving = movingAt(f);
    if (moving || owed) {
      lastBoxes = boxesAt(f);
      const r = resolveLabels(
        { boxes: lastBoxes, classOf: new Array(n).fill(60), distance: Array.from({ length: n }, (_, i) => 10 * (i + 1)), hysteresisPx: H, dropEveryPasses: DROP_EVERY, settled: false, cameraMoving: moving },
        state,
      );
      owed = r.needsFrame;
      settledAt = -1;
    } else if (settledAt < 0) {
      const r = resolveLabels(
        { boxes: lastBoxes, classOf: new Array(n).fill(60), distance: Array.from({ length: n }, (_, i) => 10 * (i + 1)), hysteresisPx: H, dropEveryPasses: DROP_EVERY, settled: true },
        state,
      );
      settledAt = f;
      final = Array.from(r.kept);
    }
    vis.push(state.wasKept[j] === 1);
  }
  return { vis, settledAt, final };
}

/** Runs of an unchanged value of length <= 5 between two changes — the motion harness's blink
 *  (review/capture-motion.mjs LABEL_BLINK_FRAMES, and the label probe's). */
function blinksOf(t: readonly boolean[]): string[] {
  const out: string[] = [];
  let start = 0;
  for (let i = 1; i <= t.length; i += 1) {
    if (i < t.length && t[i] === t[i - 1]) continue;
    const len = i - start;
    if (start > 0 && i < t.length && len <= 5) out.push(`${t[start] ? "shown" : "hidden"} ${len}f @${start}`);
    start = i;
  }
  return out;
}

describe("scene label resolver: a settled pass never reverses a change younger than the dwell (C5 residual)", () => {
  /* MEASURED (review/capture-motion.mjs, light/high/dolly-in, 2026-09-22): `access12 hidden for only
     5 frame(s) from frame 29` in a move of SIX moving frames. The name left at the start of the
     move (its dwell long run out, its box taken), and the move ended before
     LABEL_MIN_DWELL_PASSES passes had gone by; the first idle frame then ran the history-free
     settled pass (F6), which has no dwell, and put it straight back. Hysteresis is what lets the
     two passes disagree about the same final boxes: a HIDDEN name must clear its box by the margin
     to come back while the camera is (or was just) moving, the settled pass asks for no margin.

     Label 0 [0..100] outranks label 1. Label 1 sits far away, is shown for a long time, is covered
     by label 0 for two moving frames, and the camera comes to rest with label 1 two px clear of
     label 0 — clear with no margin, not clear by the hidden margin. */
  const LONG_APART = boxesOf([[0, 0, 100, 20], [300, 0, 400, 20]]);
  const COVERED = boxesOf([[0, 0, 100, 20], [0, 0, 100, 20]]);
  const NEAR = boxesOf([[0, 0, 100, 20], [102, 0, 202, 20]]);
  const MOVE_FROM = 30;

  it("precondition: at rest on the final boxes, the history-free answer shows label 1", () => {
    expect(pass(fresh(2), NEAR, true, [60, 60], [10, 20])).toEqual([1, 1]);
  });

  it("a name that left in a move shorter than the dwell is not put back by the settled pass a few frames later", () => {
    const boxesAt = (f: number): Float32Array => (f < MOVE_FROM ? LONG_APART : f < MOVE_FROM + 2 ? COVERED : NEAR);
    /* The scene ages a label per PASS, and an idle scene runs none: the long on-screen spell is a
       20-frame orbit that keeps both names clear, so label 1 is well past its dwell at the move. */
    const movingAt = (f: number): boolean => (f >= 5 && f < 25) || (f >= MOVE_FROM && f < MOVE_FROM + 3); // arrives on NEAR at MOVE_FROM + 2
    const r = sceneLoop(90, boxesAt, movingAt, 1);
    expect(r.vis[MOVE_FROM - 1], "precondition: label 1 was on screen before the move").toBe(true);
    expect(r.vis.slice(MOVE_FROM, MOVE_FROM + 3).includes(false), "precondition: label 1 left during the move").toBe(true);
    expect(blinksOf(r.vis)).toEqual([]);
    // The settled pass still happens, and still lands on the history-free answer (F6)…
    expect(r.settledAt, "the scene never reached its settled pass").toBeGreaterThan(0);
    expect(r.final).toEqual([1, 1]);
    // …no later than the dwell allows: the delay is bounded, not open-ended.
    expect(r.settledAt).toBeLessThanOrEqual(MOVE_FROM + 3 + LABEL_MIN_DWELL_PASSES + 1);
  });

  it("a name that appeared just before rest is not taken away by the settled pass a few frames later", () => {
    /* The other direction. While moving, a name already on screen outranks a new one (the
       ordering half of the hysteresis); the settled pass drops that term, so the NEARER name takes
       the box. Label 1 (farther) comes into view alone and appears; two frames later label 0
       (nearer) comes into view on the same box in a one-frame move, and the camera rests. */
    const NONE = boxesOf([null, null]);
    const ONLY1 = boxesOf([null, [0, 0, 100, 20]]);
    const SAME = boxesOf([[0, 0, 100, 20], [0, 0, 100, 20]]);
    expect(pass(fresh(2), SAME, true, [60, 60], [10, 20]), "precondition: history-free, the nearer name wins").toEqual([1, 0]);
    const ENTER = 10;
    // Where label 1 appears when nothing else happens (its temporal hold and dwell decide).
    const alone = sceneLoop(80, (f) => (f < ENTER ? NONE : ONLY1), (f) => f === ENTER, 1);
    const appeared = alone.vis.indexOf(true);
    expect(appeared, "precondition: label 1 appears on its own").toBeGreaterThan(ENTER);
    const ARRIVE = appeared + 2;
    const r = sceneLoop(
      120,
      (f) => (f < ENTER ? NONE : f < ARRIVE ? ONLY1 : SAME),
      (f) => f === ENTER || f === ARRIVE,
      1,
    );
    expect(r.vis[appeared], "precondition: label 1 appeared at the same frame").toBe(true);
    expect(blinksOf(r.vis)).toEqual([]);
    expect(r.settledAt).toBeGreaterThan(0);
    expect(r.final).toEqual([1, 0]);
  });

  it("owes no extra frame when the settled pass would agree: a young name nothing competes with does not hold the settle", () => {
    const APART2 = boxesOf([[0, 0, 100, 20], [300, 0, 400, 20]]);
    const state: LabelResolverState = { wasKept: new Uint8Array(2), pending: new Uint8Array(2), passesSinceDrop: DROP_EVERY, age: new Uint16Array(2).fill(0xffff) };
    const go = () => resolveLabels({ boxes: APART2, classOf: [60, 60], distance: [10, 20], hysteresisPx: H, dropEveryPasses: DROP_EVERY, settled: false, cameraMoving: false }, state);
    expect(go().needsFrame, "the temporal hold owes one pass").toBe(true);
    const r = go();
    expect(Array.from(r.kept), "both appeared").toEqual([1, 1]);
    expect(Array.from(state.age ?? []), "precondition: both are younger than the dwell").toEqual([0, 0]);
    expect(r.needsFrame, "young, but the settled pass would keep both: nothing to wait for").toBe(false);
  });
});
