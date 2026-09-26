/**
 * emphasis.test.ts — the first executed coverage the fabric's animation has ever had.
 *
 * WHY IT EXISTS. `converged()` is the single predicate the whole F6 capture protocol waits on, and
 * the easing it certifies had no test that ran it: `createScene` throws without a GPU, so the
 * render loop was reachable only through the "fails loudly without WebGL" case. The one test that
 * named `converged` grepped scene.ts as text; the one test double that returns it hard-codes
 * `converged: true`. A defect that made every capture frame-timing-dependent lived in that gap.
 *
 * WHAT IT PROVES. Stepping the machine to rest with DIFFERENT dt sequences leaves bit-identical
 * values in the buffer attributes the GPU reads — which is the F6 property stated as an assertion
 * instead of as a comment. The graph comes from `buildFabricGraph` over the real compiled
 * snapshot, not from a hand-built stand-in, so the instance/segment layout is the shipping one.
 *
 * WHAT IT DOES NOT PROVE. Nothing here renders. That the shader consumes `aRecede` the way this
 * value assumes is scene.test.ts's shader-patch assertions plus the capture harness, not this.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { profileFor } from "./quality";
import { buildFabricGraph } from "./scene";
import {
  HOVER_EASE,
  RECEDE_EASE,
  SELECT_EASE,
  createEaseChannel,
  stepEaseChannel,
  RECEDE_DEPTH,
  RECEDE_NEIGHBOUR,
  STILL_FRAMES_FOR_CONVERGENCE,
  createEmphasisState,
  isConverged,
  markEmphasisDirty,
  stepEmphasis,
  type EmphasisState,
} from "./emphasis";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const profile = profileFor("high");

/** The state `recomputeEmphasis` produces for "one device is the subject". */
function focusOn(graph: ReturnType<typeof buildFabricGraph>, deviceId: string): EmphasisState {
  const state = createEmphasisState(graph.order.length);
  const near = new Set(graph.neighbours.get(deviceId) ?? []);
  for (const s of graph.order) {
    state.target[s.index] = s.id === deviceId ? 0 : near.has(s.id) ? RECEDE_NEIGHBOUR : RECEDE_DEPTH;
  }
  const linkTarget = new Map<string, number>();
  for (const [id, ends] of graph.linkEnds) {
    linkTarget.set(id, ends.a === deviceId || ends.b === deviceId ? 0 : RECEDE_DEPTH);
  }
  state.linkTarget = linkTarget;
  markEmphasisDirty(state);
  return state;
}

/** Every number the GPU would read, in one flat array: devices first, then every cable segment. */
function uploaded(graph: ReturnType<typeof buildFabricGraph>): number[] {
  const out: number[] = [];
  for (const s of graph.order) {
    const attr = s.ghost ? s.group.ghostRecede : s.group.recede;
    out.push(attr === null ? Number.NaN : attr.getX(s.slot));
  }
  for (const batch of graph.cables.batches) {
    for (let i = 0; i < batch.segmentLinkIds.length; i += 1) out.push(batch.recede.getX(i));
  }
  return out;
}

/**
 * Run one emphasis animation to rest under a given frame-time sequence and report what the GPU
 * would hold. `dts` is cycled, so an irregular sequence stays irregular for the whole run.
 */
function settle(dts: readonly number[], deviceId = "core1"): { values: number[]; frames: number } {
  const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
  try {
    const state = focusOn(graph, deviceId);
    let frames = 0;
    // Bounded, and the bound is asserted: a machine that never settles must fail here rather than
    // hang the suite, because "never settles" is the other half of the defect this file guards.
    while (frames < 5000) {
      const moved = stepEmphasis(graph, state, dts[frames % dts.length] as number);
      frames += 1;
      if (!moved) break;
    }
    expect(frames, "emphasis easing did not reach rest").toBeLessThan(5000);
    return { values: uploaded(graph), frames };
  } finally {
    graph.dispose();
  }
}

const STEADY = [16.7];
const JITTERY = [8.3, 33.4, 11.2, 50.1, 16.7, 9.4, 41.8];
const COARSE = [100, 100];

describe("emphasis easing — the settled value is a function of the target, not of frame timing", () => {
  it("ends on bit-identical uploaded values under three different dt sequences", () => {
    /* THE F6 REGRESSION. Before the fix, a value inside the snap epsilon was written to the CPU
       array but not flushed, so the attribute kept `cur + (tgt-cur)*k` from whichever frame
       happened to be last — and these three runs disagreed. */
    const steady = settle(STEADY);
    const jittery = settle(JITTERY);
    const coarse = settle(COARSE);

    expect(jittery.values.length).toBe(steady.values.length);
    expect(steady.values.length).toBeGreaterThan(50);

    const disagree: string[] = [];
    for (let i = 0; i < steady.values.length; i += 1) {
      const a = steady.values[i] as number;
      const b = jittery.values[i] as number;
      const c = coarse.values[i] as number;
      if (!Object.is(a, b) || !Object.is(a, c)) disagree.push(`[${i}] ${a} / ${b} / ${c}`);
    }
    expect(
      disagree.slice(0, 8),
      `${disagree.length} uploaded values depend on frame timing:\n${disagree.slice(0, 8).join("\n")}`,
    ).toEqual([]);

    // ...and the frame COUNTS genuinely differed, so the agreement above is not three identical runs.
    expect(steady.frames).not.toBe(coarse.frames);
  });

  it("lands exactly on the target rather than near it", () => {
    /* The stronger statement, and the one that localises a failure: agreement between two runs
       could also be two runs stopping at the same wrong place. */
    const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
    try {
      const state = focusOn(graph, "core1");
      for (let i = 0; i < 5000 && stepEmphasis(graph, state, JITTERY[i % JITTERY.length] as number); i += 1);

      const wrong: string[] = [];
      for (const s of graph.order) {
        const attr = s.ghost ? s.group.ghostRecede : s.group.recede;
        if (attr === null) continue;
        const want = state.target[s.index] as number;
        const got = attr.getX(s.slot);
        if (!Object.is(got, want)) wrong.push(`${s.id}: uploaded ${got}, target ${want}`);
      }
      expect(wrong.slice(0, 8), `${wrong.length} devices settled off-target`).toEqual([]);

      for (const batch of graph.cables.batches) {
        for (let i = 0; i < batch.segmentLinkIds.length; i += 1) {
          const id = batch.segmentLinkIds[i] as string;
          const want = Math.fround(state.linkTarget.get(id) ?? 0);
          expect(batch.recede.getX(i), `segment ${i} of link ${id}`).toBe(want);
        }
      }
    } finally {
      graph.dispose();
    }
  });

  it("finishes a cable whose easing outlasts every device's", () => {
    /* Second instance of the same shape: the cable pass used to sit inside `if (deviceMoved)`, so
       a cable still travelling when the last device arrived was abandoned where it stood. Here the
       devices have nowhere to go at all and only the cables move. */
    const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
    try {
      const state = createEmphasisState(graph.order.length); // every device target 0, already there
      const linkTarget = new Map<string, number>();
      for (const [id] of graph.linkEnds) linkTarget.set(id, RECEDE_DEPTH);
      state.linkTarget = linkTarget;
      markEmphasisDirty(state);

      let frames = 0;
      while (frames < 5000 && stepEmphasis(graph, state, 16.7)) frames += 1;
      expect(frames, "cables never settled").toBeLessThan(5000);
      expect(frames, "cables settled on the first frame — they never moved").toBeGreaterThan(3);

      const want = Math.fround(RECEDE_DEPTH);
      for (const batch of graph.cables.batches) {
        for (let i = 0; i < batch.segmentLinkIds.length; i += 1) {
          expect(batch.recede.getX(i)).toBe(want);
        }
      }
    } finally {
      graph.dispose();
    }
  });

  it("reports rest exactly once the last value has been flushed", () => {
    // `stepEmphasis` returning false is what lets `dirty` stay false, which is what lets
    // `converged()` become true. A step that returns false must have nothing left to upload.
    const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
    try {
      const state = focusOn(graph, "core1");
      let frames = 0;
      while (frames < 5000 && stepEmphasis(graph, state, 16.7)) frames += 1;
      const atRest = uploaded(graph);
      for (let i = 0; i < 20; i += 1) {
        expect(stepEmphasis(graph, state, 16.7), "a settled machine reported motion").toBe(false);
      }
      expect(uploaded(graph)).toEqual(atRest);
    } finally {
      graph.dispose();
    }
  });

  it("re-targets from a half-finished ease to the same final value as from rest", () => {
    // The capture harness loads a URL; a user clicks. The second path passes through a partial
    // ease, and F6 is only worth anything if both arrive at the same picture.
    const interrupted = (() => {
      const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
      try {
        const first = focusOn(graph, "dist1");
        for (let i = 0; i < 4; i += 1) stepEmphasis(graph, first, 16.7);
        const second = focusOn(graph, "core1");
        second.current.set(first.current); // the interrupted ease carries its position forward
        let frames = 0;
        while (frames < 5000 && stepEmphasis(graph, second, 11.3)) frames += 1;
        return uploaded(graph);
      } finally {
        graph.dispose();
      }
    })();
    expect(interrupted).toEqual(settle(STEADY, "core1").values);
  });
});

describe("the convergence rule the capture harness waits on", () => {
  it("requires compiled shaders, a clean frame, still frames and a resting camera", () => {
    const settled = { compiled: true, dirty: false, stillFrames: 4, cameraTweening: false };
    expect(isConverged(settled)).toBe(true);

    // Each input is load-bearing: flip exactly one and the answer must change.
    expect(isConverged({ ...settled, compiled: false })).toBe(false);
    expect(isConverged({ ...settled, dirty: true })).toBe(false);
    expect(isConverged({ ...settled, cameraTweening: true })).toBe(false);
    expect(isConverged({ ...settled, stillFrames: STILL_FRAMES_FOR_CONVERGENCE - 1 })).toBe(false);
    expect(isConverged({ ...settled, stillFrames: STILL_FRAMES_FOR_CONVERGENCE })).toBe(true);
  });
});

/* ── C6: the recession is a FINITE ease, and settles when §4.8 says it does ───────────────────────
 *
 * The independent refuter measured THIS machine, not a channel in isolation: `stepEmphasis` at
 * 60 fps reached 99 % at 1,067 ms and settled at 1,350 ms, while §4.8 promised 240 ms — the
 * `RECEDE_MS` constant was an exponential time constant. So the settle time is asserted here on the
 * real graph, through `stepEmphasis` itself, against the row §4.8 states for `RECEDE_MS` (read from
 * the brief, not copied), and reduced motion is asserted to land every value in one frame. */
describe("C6: stepEmphasis settles within the §4.8 row for RECEDE_MS, and snaps under reduced motion", () => {
  const FRAME_60 = 1000 / 60;
  const brief = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "design-brief.md"), "utf8");
  const s48 = brief.slice(brief.indexOf("### 4.8 "), brief.indexOf("### 4.9 "));
  const row = s48.split("\n").find((l) => l.startsWith("|") && l.includes("`RECEDE_MS`"));
  const stated = Number(/settles in \*\*(\d+(?:\.\d+)?) ms\*\* at 60 fps/.exec(row ?? "")?.[1]);

  /** Frames until every uploaded value equals its target, and whether `stepEmphasis` said so. */
  function framesToTarget(reduced: boolean): { frames: number; reportedRestAt: number } {
    const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
    try {
      const state = focusOn(graph, "core1");
      const target = (): number[] => {
        const out: number[] = [];
        for (const s of graph.order) out.push(state.target[s.index] as number);
        for (const b of graph.cables.batches) for (const id of b.segmentLinkIds) out.push(Math.fround(state.linkTarget.get(id) ?? 0));
        return out;
      };
      const want = target();
      let frames = 0;
      let reportedRestAt = -1;
      while (frames < 1000) {
        stepEmphasis(graph, state, FRAME_60, reduced);
        frames += 1;
        const got = uploaded(graph);
        if (got.every((v, i) => Object.is(v, want[i]))) {
          // One more step: a machine that is AT its target must report rest.
          reportedRestAt = stepEmphasis(graph, state, FRAME_60, reduced) ? -1 : frames + 1;
          break;
        }
      }
      return { frames, reportedRestAt };
    } finally {
      graph.dispose();
    }
  }

  it("the brief states a settle time for RECEDE_MS (the check is not vacuous)", () => {
    expect(row, "§4.8 has a row naming `RECEDE_MS`").toBeDefined();
    expect(Number.isFinite(stated) && stated > 0).toBe(true);
  });

  it("every device and cable segment is exactly on target no later than §4.8 states, and under 300 ms", () => {
    const { frames, reportedRestAt } = framesToTarget(false);
    const settledMs = Math.round(frames * FRAME_60 * 1000) / 1000;
    expect(settledMs, `the recession settled at ${settledMs.toFixed(1)} ms; §4.8 states ${stated} ms`).toBeLessThanOrEqual(stated);
    expect(settledMs).toBeLessThan(300);
    // Not instantaneous either: an ease that lands in one frame is a cut, not a 240 ms dim.
    expect(frames).toBeGreaterThan(10);
    expect(reportedRestAt, "stepEmphasis kept reporting motion after every value reached its target").toBeGreaterThan(0);
  });

  it("under reduced motion every value lands on its target in the first frame", () => {
    expect(framesToTarget(true).frames).toBe(1);
  });
});

/* ── The scalar channel the hover rim and halo use: the settled value is the target, whatever dt ── */
describe("C6 / F6: an ease channel's settled value does not depend on this machine's frame timing", () => {
  const run = (dts: readonly number[], spec = SELECT_EASE): { value: number; frames: number; movingUntilLanded: boolean } => {
    const ch = createEaseChannel(0);
    let frames = 0;
    let movingUntilLanded = true;
    // Interrupted half-way: a new target starts a new ease from wherever the value is.
    for (let i = 0; i < 3; i += 1, frames += 1) stepEaseChannel(ch, spec, 0.7, dts[frames % dts.length] as number);
    while (frames < 1000) {
      const moving = stepEaseChannel(ch, spec, 0.35, dts[frames % dts.length] as number);
      frames += 1;
      if (ch.value !== 0.35 && !moving) movingUntilLanded = false;
      if (!moving) break;
    }
    return { value: ch.value, frames, movingUntilLanded };
  };

  it("lands bit-identically on the target under steady, jittery and coarse frame times", () => {
    for (const spec of [SELECT_EASE, HOVER_EASE, RECEDE_EASE]) {
      const a = run(STEADY, spec);
      const b = run(JITTERY, spec);
      const c = run(COARSE, spec);
      expect([a.value, b.value, c.value], spec.name).toEqual([0.35, 0.35, 0.35]);
      expect(a.movingUntilLanded && b.movingUntilLanded && c.movingUntilLanded, `${spec.name} reported rest before landing`).toBe(true);
      expect(a.frames, `${spec.name}: the frame counts differed, so the agreement is not three identical runs`).not.toBe(c.frames);
    }
  });
});
