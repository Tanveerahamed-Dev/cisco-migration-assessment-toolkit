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

import { resolveLabels, type LabelResolverState } from "./labelResolve";

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
