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
import { afterEach, describe, expect, it, vi } from "vitest";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { profileFor } from "./quality";
import { buildFabricGraph } from "./scene";
import * as owner from "./emphasis";
import {
  EASES,
  FADE_MAX_STEP,
  HOVER_EASE,
  RECEDE_EASE,
  SELECT_EASE,
  TIER_FADE_EASE,
  TIER_FADE_MS,
  createEaseChannel,
  createTierFade,
  createTierFadeDriver,
  easeFraction,
  stepEaseChannel,
  stepTierFade,
  type EaseChannel,
  type TierFadeHost,
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
  const run = (dts: readonly number[], spec = SELECT_EASE): { value: number; frames: number; movingUntilLanded: boolean; trajectory: number[] } => {
    const ch = createEaseChannel(0);
    let frames = 0;
    let movingUntilLanded = true;
    const trajectory: number[] = [];
    // Interrupted half-way: a new target starts a new ease from wherever the value is.
    for (let i = 0; i < 3; i += 1, frames += 1) {
      stepEaseChannel(ch, spec, 0.7, dts[frames % dts.length] as number);
      trajectory.push(ch.value);
    }
    while (frames < 1000) {
      const moving = stepEaseChannel(ch, spec, 0.35, dts[frames % dts.length] as number);
      frames += 1;
      trajectory.push(ch.value);
      if (ch.value !== 0.35 && !moving) movingUntilLanded = false;
      if (!moving) break;
    }
    return { value: ch.value, frames, movingUntilLanded, trajectory };
  };

  it("lands bit-identically on the target under steady, jittery and coarse frame times", () => {
    for (const spec of [SELECT_EASE, HOVER_EASE, RECEDE_EASE]) {
      const a = run(STEADY, spec);
      const b = run(JITTERY, spec);
      const c = run(COARSE, spec);
      expect([a.value, b.value, c.value], spec.name).toEqual([0.35, 0.35, 0.35]);
      expect(a.movingUntilLanded && b.movingUntilLanded && c.movingUntilLanded, `${spec.name} reported rest before landing`).toBe(true);
      /* Not three identical runs: the jittery run passes through different values on the way. */
      expect(b.trajectory, `${spec.name}: the jittery run took the steady run's path, so the agreement proves nothing`).not.toEqual(a.trajectory);
      /* ...and the steady and coarse runs differ in length, EXCEPT where the per-frame cap (C5,
         FADE_MAX_STEP) makes both the cap's path by construction: a LINEAR ease whose 60 Hz step
         already exceeds the cap (HOVER_MS: 16.7 / 80 = 0.21 of its span) moves exactly FADE_MAX_STEP
         per frame at 16.7 ms and at 100 ms alike — the same 9 frames, the same values. Derived from
         the spec, not from a list of names: any such ease is covered by the jittery comparison above. */
      const capBoundAt60 = spec.curve === "linear" && 1000 / 60 / spec.durationMs > FADE_MAX_STEP;
      if (capBoundAt60) expect(c.trajectory, `${spec.name}: cap-bound at 60 Hz and at 100 ms`).toEqual(a.trajectory);
      else expect(a.frames, `${spec.name}: the frame counts differed, so the agreement is not three identical runs`).not.toBe(c.frames);
    }
  });
});

/* ── C5 (2026-09-26): no fade the owner steps can move more than FADE_MAX_STEP in one frame ───────
 *
 * THE DEFECT. The quality-tier cross-fade was a CSS transition, which runs on the wall clock: a frame
 * of dt ms covers dt / 280 of its ease-in-out curve whatever the frame rate, so the per-frame step was
 * bounded only by how fast the host presents frames. MEASURED (acceptance grading at 7f67013,
 * dark/tier-fade-high-to-low-r3-nocopy): frame 33 at t=400 ms read opacity 1, frame 34 — a 116.6 ms
 * host frame — read 0.64, a 0.36 cut against the 0.25 bar. The hold before the fade cannot prevent
 * it: it predicts future frames from past ones.
 *
 * The emphasis eases had the same shape one level down: `stepEaseChannel` and `stepEmphasis` advance
 * by the frame delta, so ONE long frame (the scene clamps it to 64 ms) carried the hover rim 80 % of
 * its 80 ms ease, and the 140 ms ease-out selection rim moved 0.56 of its span on an ORDINARY 60 Hz
 * frame. The class is "a fade stepped on the clock with no per-frame bound", so the bound lives in the
 * owner and every stepper the owner exports is held to it here — the tier fade, the scalar channels
 * (hover rim, halo, and the selection rim that rides the halo) and the recession — under the frame
 * sequences that broke it: a stall on the first frame, a stall mid-fade, every frame a stall, a
 * returning tab's multi-second gap, and seeded jitter across the measured 16.7-120 ms range.
 *
 * Each step is bounded RELATIVE TO ITS EASE'S SPAN (|to - from|): the cap is a fraction of the fade,
 * so an opacity fading over [0, 1] moves at most FADE_MAX_STEP of opacity, and a derived property
 * scaled from one (the selection rim is the halo / 0.09) moves at most FADE_MAX_STEP of its own range. */

const STALL_MS = 116.6;
const pad = (head: readonly number[], n = 120): number[] => [...head, ...Array.from({ length: n - head.length }, () => 16.7)];
/** A seeded LCG, so the jitter sequence is the same on every run. */
function seededJitter(seed: number, n: number, lo = 16.7, hi = 120): number[] {
  let s = seed >>> 0;
  return Array.from({ length: n }, () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return lo + (s / 2 ** 32) * (hi - lo);
  });
}
const HOSTILE: ReadonlyArray<readonly [string, readonly number[]]> = [
  ["a stall on the first frame (the graded failure's shape)", pad([STALL_MS, 33.4])],
  ["a stall mid-fade", pad([16.7, 16.7, 16.7, 16.7, 16.7, 16.7, STALL_MS])],
  ["two stalls in a row", pad([16.7, 83.3, STALL_MS])],
  ["every frame a stall", Array.from({ length: 120 }, () => STALL_MS)],
  ["a returning tab: one 3 s gap", pad([3000])],
  ["seeded jitter 16.7-120 ms", seededJitter(0xc5, 400)],
  ["seeded jitter, second seed", seededJitter(0x2026, 400)],
];
/** Tolerance for the channel arithmetic itself (`from + (to - from) * f` in doubles / float32). */
const EPS = 1e-6;

/** Steps one scalar channel through an interrupted ease (0 -> 1, then re-targeted to 0.35 after 2
 *  frames) and returns the largest step against the span of the ease it belonged to. */
function channelSteps(spec: (typeof EASES)[number], dts: readonly number[], reduced = false) {
  const ch: EaseChannel = createEaseChannel(0);
  const worst = { ratio: 0, frame: -1 };
  let frames = 0;
  let prev = ch.value;
  for (; frames < dts.length; frames += 1) {
    const target = frames < 2 ? 1 : 0.35;
    const moving = stepEaseChannel(ch, spec, target, dts[frames]!, reduced);
    const span = Math.abs(ch.to - ch.from);
    const ratio = span === 0 ? 0 : Math.abs(ch.value - prev) / span;
    if (ratio > worst.ratio) Object.assign(worst, { ratio, frame: frames });
    prev = ch.value;
    if (!moving && frames >= 2) break;
  }
  return { worst, value: ch.value, frames: frames + 1 };
}

describe("C5: every fade the ease owner steps moves at most FADE_MAX_STEP of its span per frame", () => {
  it("the cap is a real bound under the harness's 0.25 bar, and the curve the tier fade had is kept", () => {
    expect(FADE_MAX_STEP).toBeGreaterThan(0);
    // 0.2, not 0.25: capture-motion.mjs judges the OBSERVED opacity step against its own bar.
    expect(FADE_MAX_STEP).toBeLessThanOrEqual(0.2);
    expect(TIER_FADE_EASE).toEqual({ name: "TIER_FADE_MS", durationMs: TIER_FADE_MS, curve: "ease-in-out" });
    expect(TIER_FADE_MS).toBe(280);
    // ease-in-out is CSS's cubic-bezier(0.42, 0, 0.58, 1): symmetric about its midpoint.
    expect(easeFraction("ease-in-out", 0.5)).toBeCloseTo(0.5, 9);
    expect(easeFraction("ease-in-out", 0.25) + easeFraction("ease-in-out", 0.75)).toBeCloseTo(1, 9);
  });

  for (const [name, dts] of HOSTILE) {
    it(`the tier cross-fade under ${name}: every step <= FADE_MAX_STEP, never back up, lands exactly on 0`, () => {
      const fade = createTierFade();
      expect(fade.value).toBe(1);
      let prev = 1;
      let worst = 0;
      let frames = 0;
      for (; frames < dts.length; frames += 1) {
        const moving = stepTierFade(fade, dts[frames]!);
        expect(fade.value, `frame ${frames}: the fade went back up`).toBeLessThanOrEqual(prev);
        worst = Math.max(worst, prev - fade.value);
        prev = fade.value;
        if (!moving) break;
      }
      expect(worst, `${name}: one frame stepped ${worst.toFixed(3)}`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      expect(fade.value, "the fade did not land on 0 exactly").toBe(0);
      // A cap binds for at least 1 / FADE_MAX_STEP frames: never a cut, whatever the host did.
      expect(frames + 1).toBeGreaterThanOrEqual(Math.ceil(1 / FADE_MAX_STEP));
    });

    it(`every scalar ease (${EASES.map((e) => e.name).join(", ")}) under ${name}: every step <= FADE_MAX_STEP of its span, lands on target`, () => {
      for (const spec of EASES) {
        const r = channelSteps(spec, dts);
        expect(r.worst.ratio, `${spec.name}: frame ${r.worst.frame} stepped ${r.worst.ratio.toFixed(3)} of its span`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
        expect(r.value, `${spec.name} did not land on its target`).toBe(0.35);
      }
    });

    it(`the recession (stepEmphasis, every device and cable segment) under ${name}: every step <= FADE_MAX_STEP of its span`, () => {
      const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile });
      try {
        const state = focusOn(graph, "core1");
        const start = uploaded(graph);
        const want = [
          ...graph.order.map((s) => state.target[s.index] as number),
          ...graph.cables.batches.flatMap((b) => b.segmentLinkIds.map((id) => Math.fround(state.linkTarget.get(id) ?? 0))),
        ];
        const spans = start.map((v, i) => Math.abs((want[i] as number) - v));
        let prev = start;
        let worst = { ratio: 0, at: "" };
        for (let frames = 0; frames < dts.length; frames += 1) {
          const moved = stepEmphasis(graph, state, dts[frames]!);
          const now = uploaded(graph);
          for (let i = 0; i < now.length; i += 1) {
            const span = spans[i] as number;
            if (span === 0) continue;
            const ratio = Math.abs((now[i] as number) - (prev[i] as number)) / span;
            if (ratio > worst.ratio) worst = { ratio, at: `value ${i}, frame ${frames}` };
          }
          prev = now;
          if (!moved) break;
        }
        expect(worst.ratio, `${name}: ${worst.at} stepped ${worst.ratio.toFixed(3)} of its span`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
        expect(prev.every((v, i) => Object.is(v, want[i])), "the recession did not land exactly on its targets").toBe(true);
      } finally {
        graph.dispose();
      }
    });
  }

  it("at 60 Hz the cap never binds on the tier fade: it IS the 280 ms ease-in-out, done on the first frame at or after 280 ms", () => {
    const fade = createTierFade();
    const DT = 1000 / 60;
    let frames = 0;
    let worst = 0;
    let prev = 1;
    while (frames < 100 && fade.value > 0) {
      stepTierFade(fade, DT);
      frames += 1;
      if (fade.value > 0) expect(fade.value).toBeCloseTo(1 - easeFraction("ease-in-out", (frames * DT) / TIER_FADE_MS), 12);
      worst = Math.max(worst, prev - fade.value);
      prev = fade.value;
    }
    expect(fade.value).toBe(0);
    // 17 frames = 283.3 ms: the first frame at or after 280 ms, and under C6's 300 ms.
    expect(frames).toBe(Math.ceil(TIER_FADE_MS / DT));
    expect(worst, "the largest ordinary-frame step (0.103 by the model)").toBeLessThan(0.11);
  });

  it("at 30 Hz the tier fade still finishes within one frame of 280 ms", () => {
    const fade = createTierFade();
    const DT = 1000 / 30;
    let frames = 0;
    while (frames < 100 && fade.value > 0) {
      stepTierFade(fade, DT);
      frames += 1;
    }
    expect(frames * DT).toBeGreaterThanOrEqual(TIER_FADE_MS);
    expect(frames * DT).toBeLessThan(TIER_FADE_MS + DT);
  });

  it("the graded failure's exact frame sequence: the CSS model stepped 0.36; the stepper steps at most the cap", () => {
    /* report.json at 7f67013, dark/tier-fade-high-to-low-r3-nocopy: the fade effectively started at
       t=400 (frame 33) and the frames after it were 116.6, 33.4, 16.6, 16.7, 16.7, 16.6, 16.7 ms. The
       CSS transition's opacity is 1 - E((t - 400) / 280) and reproduces every recorded sample. */
    const dts = [116.6, 33.4, 16.6, 16.7, 16.7, 16.6, 16.7, 16.7, 16.7, 16.7, 16.7, 16.7, 16.7, 16.7, 16.7, 16.7, 16.7];
    const css = (t: number): number => 1 - easeFraction("ease-in-out", t / TIER_FADE_MS);
    expect(Math.round((1 - css(116.6)) * 100) / 100, "the model reproduces the graded 0.36 cut").toBe(0.36);
    const fade = createTierFade();
    let prev = 1;
    let worst = 0;
    for (const dt of dts) {
      stepTierFade(fade, dt);
      worst = Math.max(worst, prev - fade.value);
      prev = fade.value;
      if (fade.value === 0) break;
    }
    expect(worst).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
    expect(fade.value).toBe(0);
  });

  it("reduced motion keeps its documented behaviour: every fade lands on its target in the frame it starts (a swap)", () => {
    const fade = createTierFade();
    stepTierFade(fade, 16.7, true);
    expect(fade.value).toBe(0);
    for (const spec of EASES) {
      const ch = createEaseChannel(0);
      stepEaseChannel(ch, spec, 1, 16.7, true);
      expect(ch.value, spec.name).toBe(1);
    }
  });

  it("the owner's denominator: every stepper it exports is driven above (a new stepper cannot skip the cap test)", () => {
    const drivers = ["stepEaseChannel", "stepEmphasis", "stepTierFade"];
    const steppers = Object.entries(owner)
      .filter(([k, v]) => typeof v === "function" && /^step[A-Z]/.test(k))
      .map(([k]) => k)
      .sort();
    expect(steppers).toEqual(drivers);
  });
});

/* ── The driver the scene runs the overlay with (C5 verification, 2026-09-26) ──────────────────────
 *
 * The stepper above is the per-frame bound. The scene's part (step once per frame on the RAW frame
 * duration, write the overlay's opacity, remove the overlay on the frame the fade reaches exactly 0,
 * and a no-frames watchdog that needs TWO idle windows) used to be inline in scene.ts. There it was
 * pinned only by source-text regexes. A verifier's mutations stopped the fade from ever stepping
 * (the overlay then sat at opacity 1 until the watchdog cut it at 2.4 s) and made the watchdog
 * one-strike, and every unit test still passed. It is now `createTierFadeDriver`, executed here with
 * fake timers. scene.test.ts pins that `frame()` calls it unconditionally, on `raw`. */
describe("C5: the tier-fade driver: step on raw, write, remove at exactly 0, and a two-window no-frames watchdog", () => {
  const WINDOW = 1200;
  afterEach(() => {
    vi.useRealTimers();
  });
  function drive() {
    vi.useFakeTimers();
    const writes: number[] = [];
    let finished = 0;
    const host: TierFadeHost = {
      watchdogMs: WINDOW,
      write: (v) => writes.push(v),
      finish: () => {
        finished += 1;
      },
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    };
    const d = createTierFadeDriver(host);
    return { d, writes, finished: () => finished };
  }

  it("arms its watchdog when the fade starts, and a stalled frame moves the overlay by the cap, not by the wall clock", () => {
    const { d, writes } = drive();
    expect(vi.getTimerCount(), "the no-frames watchdog is armed").toBe(1);
    expect(d.frame(116.6, false)).toBe(true);
    // The wall-clock curve would be at 1 - E(116.6 / 280) = 0.64 (the graded cut); the 64 ms clamp at ~0.9.
    expect(writes).toEqual([1 - FADE_MAX_STEP]);
  });

  it("writes every frame's value and removes the overlay exactly once, on the frame it reaches exactly 0", () => {
    const { d, writes, finished } = drive();
    let frames = 0;
    while (d.frame(1000 / 60, false)) {
      frames += 1;
      expect(finished(), "removed while the fade was still above 0").toBe(0);
      expect(frames).toBeLessThan(100);
    }
    expect(finished()).toBe(1);
    expect(d.value).toBe(0);
    expect(writes.length, "one write per frame before the last").toBe(frames);
    expect(writes.every((v) => v > 0 && v < 1)).toBe(true);
    for (let i = 1; i < writes.length; i += 1) expect(writes[i]!).toBeLessThanOrEqual(writes[i - 1]!);
    // Done means done: a later frame neither writes nor removes again, and no timer is left behind.
    expect(d.frame(16.7, false)).toBe(false);
    expect(writes.length).toBe(frames);
    expect(finished()).toBe(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ONE idle window (a main-thread stall longer than the window) does not remove a half-faded overlay", () => {
    const { d, finished } = drive();
    d.frame(1000 / 60, false);
    d.frame(1000 / 60, false);
    // The first window saw those frames; the second sees none (one strike).
    vi.advanceTimersByTime(WINDOW);
    vi.advanceTimersByTime(WINDOW);
    expect(finished(), "one strike removed the overlay").toBe(0);
    // The frame that was already due arrives, and the fade carries on to its end.
    for (let i = 0; i < 100 && d.frame(1000 / 60, false); i += 1);
    expect(finished()).toBe(1);
  });

  it("frames arriving between windows reset the count: a slow but live host is never cut by the watchdog", () => {
    const { d, finished } = drive();
    for (let i = 0; i < 3; i += 1) {
      vi.advanceTimersByTime(WINDOW);
      expect(finished()).toBe(0);
      d.frame(WINDOW, false);
    }
    expect(finished()).toBe(0);
    expect(d.value).toBeCloseTo(1 - 3 * FADE_MAX_STEP, 9);
  });

  it("TWO consecutive idle windows (rAF suspended: a hidden tab) remove it, once", () => {
    const { d, finished } = drive();
    d.frame(1000 / 60, false);
    // The window the frame fell in, then two without one.
    vi.advanceTimersByTime(WINDOW);
    expect(finished()).toBe(0);
    vi.advanceTimersByTime(WINDOW);
    expect(finished(), "one strike removed the overlay").toBe(0);
    vi.advanceTimersByTime(WINDOW);
    expect(finished()).toBe(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(d.frame(16.7, false)).toBe(false);
    expect(finished()).toBe(1);
  });

  it("a fade that never gets a frame at all is removed after two windows", () => {
    const { finished } = drive();
    vi.advanceTimersByTime(WINDOW);
    expect(finished()).toBe(0);
    vi.advanceTimersByTime(WINDOW);
    expect(finished()).toBe(1);
  });

  it("dispose (the scene removed the overlay itself) stops the watchdog: nothing is removed twice", () => {
    const { d, finished } = drive();
    d.frame(1000 / 60, false);
    d.dispose();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * WINDOW);
    expect(finished()).toBe(0);
    expect(d.frame(16.7, false)).toBe(false);
  });

  it("reduced motion: the overlay is removed on the first frame (a swap, never an animation)", () => {
    const { d, writes, finished } = drive();
    expect(d.frame(16.7, true)).toBe(false);
    expect(writes).toEqual([]);
    expect(finished()).toBe(1);
  });
});

/* ── The envelope TIER_FADE_MS's comment states: when the cap delays the tier fade ─────────────────
 * The claim is pinned here rather than left as prose. An earlier version said a fade overruns 300 ms
 * only on "a host that presents fewer than about five frames in 300 ms". An independent run
 * contradicted it with 316.6 / 316.7 ms fades that had 12-13 frames each. Each case below is 60 Hz
 * frames with ONE long frame, at every placement, measured the way review/capture-motion.mjs
 * measures a fade: from the frame before the value leaves 0.995 to the frame it is <= 0.005. */
describe("C5: when the per-frame cap delays the tier fade (the envelope TIER_FADE_MS states)", () => {
  const F = 1000 / 60;
  /** [fade duration, whether the cap bound] for 60 Hz frames with one `stallMs` frame at index k. */
  function measure(k: number, stallMs: number, capped: boolean): [number, boolean] {
    const fade = createTierFade();
    const ts = [0];
    const vs = [1];
    let t = 0;
    let bound = false;
    for (let i = 0; i < 60 && fade.value > 0; i += 1) {
      const dt = i === k ? stallMs : F;
      t += dt;
      if (capped) stepTierFade(fade, dt);
      else fade.value = 1 - easeFraction("ease-in-out", t / TIER_FADE_MS);
      if (capped && Math.abs(fade.value - (1 - easeFraction("ease-in-out", t / TIER_FADE_MS))) > 1e-9) bound = true;
      ts.push(t);
      vs.push(Math.max(0, fade.value));
    }
    const s = vs.findIndex((v) => v < 0.995);
    const e = vs.findIndex((v, i) => i >= s && v <= 0.005);
    return [ts[e]! - ts[s - 1]!, bound];
  }
  const worstExtraFrames = (stallMs: number): number =>
    Math.max(...Array.from({ length: 18 }, (_, k) => Math.round((measure(k, stallMs, true)[0] - measure(k, stallMs, false)[0]) / F)));

  it("a frame under 33 ms never engages the cap; a 34 ms frame on the steep part does (one dropped frame can)", () => {
    expect(Array.from({ length: 18 }, (_, k) => measure(k, 32, true)[1]).some(Boolean)).toBe(false);
    expect(Array.from({ length: 18 }, (_, k) => measure(k, 34, true)[1]).some(Boolean)).toBe(true);
  });

  it("the cap adds at most one 60 Hz frame for an 83-100 ms stall, two for 116-133 ms, four for 200-250 ms", () => {
    expect(Math.max(worstExtraFrames(83.3), worstExtraFrames(100))).toBe(1);
    expect(Math.max(worstExtraFrames(116.6), worstExtraFrames(133.4))).toBe(2);
    expect(Math.max(worstExtraFrames(200), worstExtraFrames(250))).toBe(4);
  });

  it("the wall-clock fade itself (the old CSS one) already reaches 300 ms on one 50 ms frame among its last", () => {
    const worst = Math.max(...Array.from({ length: 18 }, (_, k) => measure(k, 50, false)[0]));
    expect(worst).toBeGreaterThanOrEqual(300 - 0.5);
  });
});
