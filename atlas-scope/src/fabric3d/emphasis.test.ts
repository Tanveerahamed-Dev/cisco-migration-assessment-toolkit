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
  createTierFadeSlot,
  easeFraction,
  stepEaseChannel,
  stepTierFade,
  handOverTierFade,
  tierFadeCopy,
  type EaseChannel,
  type EaseSpec,
  type TierFadeCopy,
  type TierFadeHoldHandle,
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
/* The emphasis subjects, chosen BY PROPERTY (P3C-V2-3): FOCUS is the collected device with the most distinct
   neighbours (a hub, so a focus recedes a real neighbourhood), SECOND its best-connected collected neighbour (the
   interrupted-ease case moves the focus between two adjacent devices). They used to be typed ("core1", "dist1"): on
   any other dataset those named no device, every node receded to depth, and the tests ran a weaker case than they
   claim while staying green. */
const neighboursOf = (id: string): Set<string> =>
  new Set((fabricJson.links as Link[]).flatMap((l) => (l.a === id ? [l.b] : l.b === id ? [l.a] : [])));
const byReach = (a: Device, b: Device): number => neighboursOf(b.id).size - neighboursOf(a.id).size || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
const FOCUS: string = [...devices].filter((d) => d.collected).sort(byReach)[0]?.id ?? devices[0]!.id;
const SECOND: string = [...devices].filter((d) => d.collected && d.id !== FOCUS && neighboursOf(FOCUS).has(d.id)).sort(byReach)[0]?.id ?? devices[1]!.id;
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
function settle(dts: readonly number[], deviceId = FOCUS): { values: number[]; frames: number } {
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
      const state = focusOn(graph, FOCUS);
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
      const state = focusOn(graph, FOCUS);
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
        const first = focusOn(graph, SECOND);
        for (let i = 0; i < 4; i += 1) stepEmphasis(graph, first, 16.7);
        const second = focusOn(graph, FOCUS);
        second.current.set(first.current); // the interrupted ease carries its position forward
        let frames = 0;
        while (frames < 5000 && stepEmphasis(graph, second, 11.3)) frames += 1;
        return uploaded(graph);
      } finally {
        graph.dispose();
      }
    })();
    expect(interrupted).toEqual(settle(STEADY, FOCUS).values);
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
      const state = focusOn(graph, FOCUS);
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
        const state = focusOn(graph, FOCUS);
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

  it("where the cap binds at 60 Hz is what the owner's doctrine says: the first frames of HOVER_MS, RECEDE_MS and SELECT_MS, never TIER_FADE_MS, never a landing frame", () => {
    /* C5-R2-4 (verifier round 2): the doctrine said the cap "does not bind on the last frames of any
       ease here at 60 Hz", while HOVER_MS (80 ms linear: 16.7 / 80 = 0.208 of its span per frame) is
       held to the cap on every 60 Hz frame but its landing one. The prose now states the measured
       set; this computes it over EVERY EaseSpec the owner exports and holds the prose to it. */
    const DT = 1000 / 60;
    const specs = Object.values(owner).filter(
      (v): v is EaseSpec => typeof v === "object" && v !== null && typeof (v as EaseSpec).durationMs === "number" && typeof (v as EaseSpec).curve === "string",
    );
    expect(specs.map((e) => e.name).sort()).toEqual(["HOVER_MS", "RECEDE_MS", "SELECT_MS", "TIER_FADE_MS"]);
    const boundFrames = new Map<string, number[]>();
    for (const spec of specs) {
      const ch = createEaseChannel(0);
      const bound: number[] = [];
      let frames = 0;
      while (frames < 100 && ch.value !== 1) {
        stepEaseChannel(ch, spec, 1, DT);
        frames += 1;
        const onCurve = frames * DT >= spec.durationMs ? 1 : easeFraction(spec.curve, (frames * DT) / spec.durationMs);
        if (ch.fraction < onCurve - 1e-12) bound.push(frames);
      }
      // Never on the landing frame: every ease lands on the first 60 Hz frame at or after its duration.
      expect(frames, `${spec.name} lands on the frame its uncapped curve does`).toBe(Math.ceil(spec.durationMs / DT - 1e-9));
      expect(bound, `${spec.name}: the cap bound on its landing frame`).not.toContain(frames);
      boundFrames.set(spec.name, bound);
    }
    expect(Object.fromEntries(boundFrames)).toEqual({ HOVER_MS: [1, 2, 3, 4], RECEDE_MS: [1, 2, 3, 4], SELECT_MS: [1, 2, 3, 4], TIER_FADE_MS: [] });
    // HOVER_MS is held to the cap on every frame but its landing one.
    expect(boundFrames.get("HOVER_MS")!.length).toBe(Math.ceil(HOVER_EASE.durationMs / DT) - 1);
    const doctrine = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "emphasis.ts"), "utf8").replace(/\s*\n\s*\*\s?/g, " ");
    expect(doctrine, "the old claim is gone").not.toMatch(/does not bind on the last frames of any ease/);
    expect(doctrine).toMatch(/HOVER_MS[^.]*on every 60 Hz frame but its last/);
    for (const [name, frames] of boundFrames) {
      if (frames.length > 0) expect(doctrine, `the doctrine names ${name} among the eases the cap binds at 60 Hz`).toMatch(new RegExp(`binds at 60 Hz on the first ${frames.length} frames of [^.]*${name}`));
    }
    expect(doctrine).toMatch(/never on TIER_FADE_MS/);
  });
});

/* ── The driver the scene runs the overlay with (C5 verification, 2026-09-26; C5-R2-1, 2026-09-27) ─
 *
 * The stepper above is the per-frame bound. The scene's part (step once per frame on the RAW frame
 * duration, write the overlay's opacity, remove the overlay on the frame the fade reaches exactly 0)
 * used to be inline in scene.ts. There it was pinned only by source-text regexes. A verifier's
 * mutations stopped the fade from ever stepping and every unit test still passed. It is now
 * `createTierFadeDriver`, executed here. scene.test.ts pins that `frame()` calls it unconditionally,
 * on `raw`.
 *
 * NO WATCHDOG (C5-R2-1, owner decision 2026-09-27: "no path — tier change mid-fade, the tab-switch
 * step-up, a reduced-motion toggle … — may remove, replace or reset a fade overlay faster than the
 * per-frame cap"). The driver used to own a no-frames watchdog that removed the overlay after two
 * 1,200 ms windows without a frame (a hidden tab). Its tests below asserted that removal. It is the
 * one path by which the driver removed an overlay above 0: hidden for 2.4 s or more, the reader came
 * back to a picture that had lost a half-faded overlay between two presented frames — a cut of the
 * overlay's whole remaining opacity. Nothing is lost without it: every presented frame is a `frame()`
 * call, so the fade ends at most ceil(1 / FADE_MAX_STEP) frames after frames resume, and while none
 * come nothing is presented. Those tests are therefore inverted here, not dropped: the same idle
 * windows, and the removal they asserted is now asserted NOT to happen, with the first frame back
 * held to the cap. */
describe("C5: the tier-fade driver: step on raw, write, remove at exactly 0 — and nothing else removes it", () => {
  const WINDOW = 1200;
  afterEach(() => {
    vi.useRealTimers();
  });
  function drive() {
    vi.useFakeTimers();
    const writes: number[] = [];
    let finished = 0;
    const host: TierFadeHost = {
      write: (v) => writes.push(v),
      finish: () => {
        finished += 1;
      },
    };
    const d = createTierFadeDriver(host);
    return { d, writes, finished: () => finished };
  }

  it("arms no timer: only a frame moves or removes the overlay, and a stalled frame moves it by the cap, not by the wall clock", () => {
    const { d, writes } = drive();
    expect(vi.getTimerCount(), "a timer of its own could remove the overlay between two presented frames").toBe(0);
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

  it("a hidden tab (no frames for 1, 2 or 10 of the old watchdog's windows) never removes a half-faded overlay; the first frame back moves it by the cap", () => {
    for (const windows of [1, 2, 10]) {
      const { d, writes, finished } = drive();
      d.frame(1000 / 60, false);
      d.frame(1000 / 60, false);
      const before = d.value;
      expect(before).toBeGreaterThan(0.5);
      vi.advanceTimersByTime(windows * WINDOW);
      expect(finished(), `${windows} idle window(s) removed the overlay`).toBe(0);
      expect(writes.length, "nothing wrote the overlay while no frame came").toBe(2);
      // The frame the browser runs on return carries the whole hidden span as its duration.
      expect(d.frame(windows * WINDOW, false)).toBe(true);
      expect(before - d.value, "the first frame back moved more than the cap").toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      let frames = 1;
      for (; frames < 100 && d.frame(1000 / 60, false); frames += 1);
      expect(finished()).toBe(1);
      expect(frames, "after the return the fade ends within ceil(1 / FADE_MAX_STEP) frames").toBeLessThanOrEqual(Math.ceil(1 / FADE_MAX_STEP));
      vi.useRealTimers();
    }
  });

  it("frames arriving a window apart (a slow but live host) move it by the cap each and never cut it", () => {
    const { d, finished } = drive();
    for (let i = 0; i < 3; i += 1) {
      vi.advanceTimersByTime(WINDOW);
      expect(finished()).toBe(0);
      d.frame(WINDOW, false);
    }
    expect(finished()).toBe(0);
    expect(d.value).toBeCloseTo(1 - 3 * FADE_MAX_STEP, 9);
  });

  it("a fade that gets no frame at all stays at 1 (nothing is presented), and fades by the cap from its first frame", () => {
    const { d, writes, finished } = drive();
    vi.advanceTimersByTime(10 * WINDOW);
    expect(finished()).toBe(0);
    expect(d.value).toBe(1);
    expect(d.frame(10 * WINDOW, false)).toBe(true);
    expect(writes).toEqual([1 - FADE_MAX_STEP]);
  });

  it("a frame that presents nothing new (the canvas warming up) holds the fade where it is; the next presented frame moves it by the cap at most", () => {
    /* R4-V1-4 (verifier, 2026-09-27): a fade kept across a tier change that lands during a warm-up
       went on stepping while nothing new was presented (the warm-up renders no frame), so it could
       reach 0 and leave before the new tier's first frame — which then landed with no overlay at all,
       the whole pop the fade exists to hide. While the canvas presents nothing new the fade holds. */
    const { d, writes, finished } = drive();
    d.frame(1000 / 60, false);
    d.frame(1000 / 60, false);
    const at = d.value;
    expect(at).toBeGreaterThan(0.5);
    expect(at).toBeLessThan(1);
    for (const raw of [1000 / 60, 116.6, 3000]) {
      for (const reduced of [false, true]) {
        expect(d.frame(raw, reduced, false), "the overlay stays up while nothing new is presented").toBe(true);
        expect(d.value, `a ${raw} ms frame that presented nothing moved the fade (reduced ${reduced})`).toBe(at);
      }
    }
    expect(finished()).toBe(0);
    expect(writes.length, "nothing to write while it holds").toBe(2);
    expect(d.frame(1000 / 60, false, true)).toBe(true);
    expect(d.value).toBeLessThan(at);
    expect(at - d.value).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
    // A fade that has not taken its first step holds at 1 too: no reduced-motion swap on a frame that presents nothing.
    const fresh = drive();
    expect(fresh.d.frame(1000 / 60, true, false)).toBe(true);
    expect(fresh.d.value).toBe(1);
    expect(fresh.finished()).toBe(0);
  });

  it("dispose (the scene removed or replaced the overlay itself) is final: later frames neither write nor remove", () => {
    const { d, writes, finished } = drive();
    d.frame(1000 / 60, false);
    d.dispose();
    d.dispose();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * WINDOW);
    expect(finished()).toBe(0);
    expect(d.frame(16.7, false)).toBe(false);
    expect(writes.length).toBe(1);
  });

  it("reduced motion from the fade's first frame: the overlay, still at exactly 1, leaves at the cap per frame — never in one frame (R4-VR2-4)", () => {
    /* A driver starts only through a hold the slot handed out on `presented(false)`: the overlay was on screen
       under FULL motion. A reduced flag on its first frame is therefore a reduced-motion TOGGLE, one of the
       owner's named paths (C5-R2-1), and it may not take the overlay down faster than the cap. It used to
       swap 1 -> 0 in one frame (verifier round 2 of R4: "the slot then swaps the overlay away in one frame,
       uncovering the whole tier pop"). §4.8's swap at exactly 1 is the slot's, for an overlay never shown
       under full motion (below). */
    const { d, writes, finished } = drive();
    let prev = 1;
    let frames = 0;
    for (; frames < 20 && d.frame(16.7, true); frames += 1) {
      expect(prev - d.value, `frame ${frames}`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      prev = d.value;
    }
    expect(prev - d.value, "the last step to 0").toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
    expect(frames + 1).toBe(Math.ceil(1 / FADE_MAX_STEP - EPS));
    expect(writes.every((v) => v > 0 && v < 1)).toBe(true);
    expect(finished()).toBe(1);
  });

  it("reduced motion switched on MID-FADE hands over from the current value: the rest leaves at the cap per frame, never in one frame", () => {
    /* C5-R2-1: a reduced-motion toggle is one of the owner's named paths. The old driver swapped to 0
       from wherever the fade was — measured here, 0.87 -> 0 in one frame. In the product this flag
       reaches a running fade only through scene.ts `setReducedMotion`; which route a toggle takes in
       the host is read from Fabric3D.tsx by scene.test.ts. */
    const { d, writes, finished } = drive();
    for (let i = 0; i < 6; i += 1) d.frame(1000 / 60, false);
    const mid = d.value;
    expect(mid).toBeGreaterThan(FADE_MAX_STEP);
    expect(mid).toBeLessThan(1);
    let prev = mid;
    let frames = 0;
    for (; frames < 20 && d.frame(16.7, true); frames += 1) {
      expect(prev - d.value, `frame ${frames} after the toggle`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      prev = d.value;
    }
    expect(prev - d.value, "the last step to 0").toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
    expect(finished()).toBe(1);
    // ...and it does leave at the cap: no dawdling on the curve once motion is to be reduced.
    expect(frames + 1).toBe(Math.ceil(mid / FADE_MAX_STEP - EPS));
    expect(writes.every((v) => v > 0 && v < 1)).toBe(true);
  });
});

/* ── Handing a running cross-fade over to the next one (C5-R2-1, 2026-09-27) ───────────────────────
 *
 * The defect (verifier round 2, C5-R2-1): a tier change that lands while a cross-fade runs — a
 * `setQuality` mid-fade, or the step-up a tab switch queues for the first frame back — ran
 * `snapshotForTierFade`, which called `clearTierFade()` first, whatever the overlay's opacity. The
 * half-faded overlay vanished in one frame and a fresh copy of the canvas UNDER it took its place:
 * the screen dropped by the overlay's whole remaining opacity (0.4-1.0 of the tier pop) at once.
 *
 * The rule now (`handOverTierFade`, the ease owner): the new overlay is a copy of the frame the canvas
 * shows, with the RUNNING overlay drawn over it at its CURRENT opacity, so at opacity 1 it shows
 * exactly the picture the reader saw; the old one leaves in the same task. While a warm-up runs no
 * copy can be taken: a FADING overlay then defers the tier change until the warm-up has presented
 * (R4-VR1-5), and a held one waits for the new tier's first frame again. Only a copy that fails
 * outright (no 2-D context, a draw that throws) KEEPS a fading overlay running from its value. The
 * compose itself (`tierFadeCopy`, what scene.ts hands the handover) is run
 * against a compositing 2-D context below; `picCopy` is this file's shorthand for it. */
type Pic = { pic: number };
const picCopy = (canvasPic: number, draws?: [Pic, number][]) => (): TierFadeCopy<Pic> => {
  const el: Pic = { pic: canvasPic };
  return {
    el,
    drawOver(overlay, alpha) {
      draws?.push([overlay, alpha]);
      el.pic = alpha * overlay.pic + (1 - alpha) * el.pic;
      return true;
    },
  };
};

describe("C5-R2-1: a new tier cross-fade hands over from the running one's CURRENT value", () => {
  it("with nothing up, a tier change mounts a copy of the old tier's frame (or nothing, when none can be taken)", () => {
    const h = handOverTierFade<Pic>(null, picCopy(0.3));
    expect(h.kind).toBe("new");
    expect(h.kind === "new" && h.mount.pic).toBe(0.3);
    expect(handOverTierFade<Pic>(null, () => null)).toEqual({ kind: "none" });
  });

  it("a running overlay at 0.46 is composed into the copy at 0.46 and replaced by it: the new overlay shows what was on screen", () => {
    const running: Pic = { pic: 0.9 };
    const draws: [Pic, number][] = [];
    const canvas = 0.2;
    const h = handOverTierFade<Pic>({ el: running, opacity: 0.46, fading: true }, picCopy(canvas, draws));
    expect(h.kind).toBe("composed");
    if (h.kind !== "composed") return;
    expect(draws).toEqual([[running, 0.46]]);
    expect(h.from).toBe(0.46);
    expect(h.remove).toBe(running);
    const onScreenBefore = 0.46 * running.pic + (1 - 0.46) * canvas;
    // At opacity 1 over the same canvas, the new overlay IS the picture the reader saw.
    expect(h.mount.pic).toBeCloseTo(onScreenBefore, 12);
  });

  it("a held overlay (opacity 1) is composed at 1: the new overlay is the held picture itself", () => {
    const held: Pic = { pic: 0.7 };
    const h = handOverTierFade<Pic>({ el: held, opacity: 1, fading: false }, picCopy(0.1));
    expect(h.kind === "composed" && h.mount.pic).toBe(0.7);
  });

  it("no copy possible: the running overlay is KEPT as it is — a fading one carries on, a held one waits for the new tier again", () => {
    expect(handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 0.4, fading: true }, () => null)).toEqual({ kind: "kept", from: 0.4, rehold: false });
    expect(handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 1, fading: false }, () => null)).toEqual({ kind: "kept", from: 1, rehold: true });
    // A copy that cannot draw the running overlay is no copy: nothing is swapped for a partial picture.
    const failing = (): TierFadeCopy<Pic> => ({ el: { pic: 0 }, drawOver: () => false });
    expect(handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 0.4, fading: true }, failing)).toEqual({ kind: "kept", from: 0.4, rehold: false });
  });

  it("a warm-up in progress: a FADING overlay defers the tier change (no copy is asked for); a held one waits again; nothing up is `none` (R4-VR1-5)", () => {
    /* R4-VR1-5 (verifier, 2026-09-27): a tier change during a theme change's or new data's warm-up
       while a fade ran was `kept`, and the new tier's first frame then landed under the fade's partial
       value: (1 - that value) of the pop uncovered in one frame. It now waits until a copy can be
       taken, and is handed over from the value the fade held meanwhile. */
    let asked = 0;
    const counting = (): TierFadeCopy<Pic> | null => {
      asked += 1;
      return null;
    };
    expect(handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 0.4, fading: true }, counting, true)).toEqual({ kind: "deferred", from: 0.4 });
    expect(handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 1, fading: false }, counting, true)).toEqual({ kind: "kept", from: 1, rehold: true });
    expect(handOverTierFade<Pic>(null, counting, true)).toEqual({ kind: "none" });
    expect(asked, "no copy is attempted while the canvas warms up (it would re-present a half-built chain)").toBe(0);
    // Not warming: the same fading overlay is composed as before.
    expect(handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 0.4, fading: true }, picCopy(0), false).kind).toBe("composed");
  });

  it("the scene's compose step (tierFadeCopy): the running overlay is painted over the WHOLE copy at its current opacity, and the painter is left at alpha 1", () => {
    /* R4-V1-2 (verifier, 2026-09-27): the compose was inline in scene.ts (`drawOver`), reached by no
       unit test — `globalAlpha = 1` in place of the overlay's opacity kept every test green while a
       mid-fade handover at 0.54 moved the screen by 0.85 of a removal. scene.ts now returns
       `tierFadeCopy(el, ctx, w, h)` (pinned in scene.test.ts), and it runs here against a scalar 2-D
       context that composites the way a canvas does: source-over at the context's globalAlpha. */
    const W = 640;
    const H = 400;
    for (const alpha of [0, 0.05, 0.46, 0.54, 1]) {
      const canvasPic = 0.2;
      const running: Pic = { pic: 0.9 };
      const target: Pic = { pic: canvasPic };
      const calls: unknown[][] = [];
      const painter = {
        globalAlpha: 1,
        drawImage(img: Pic, dx: number, dy: number, dw: number, dh: number): void {
          calls.push([img, painter.globalAlpha, dx, dy, dw, dh]);
          const covered = dx <= 0 && dy <= 0 && dx + dw >= W && dy + dh >= H ? 1 : 0;
          target.pic = covered * painter.globalAlpha * img.pic + (1 - covered * painter.globalAlpha) * target.pic;
        },
      };
      const h = handOverTierFade<Pic>({ el: running, opacity: alpha, fading: alpha < 1 }, () => tierFadeCopy(target, painter, W, H));
      expect(h.kind, `alpha ${alpha}`).toBe("composed");
      expect(calls, `alpha ${alpha}: one draw of the running overlay, at its opacity, over the whole copy`).toEqual([[running, alpha, 0, 0, W, H]]);
      expect(painter.globalAlpha, "the context is left at alpha 1").toBe(1);
      const onScreen = alpha * running.pic + (1 - alpha) * canvasPic;
      expect(h.kind === "composed" && h.mount.pic, `alpha ${alpha}: the new overlay at 1 is the picture on screen`).toBeCloseTo(onScreen, 12);
    }
    // A context that throws while drawing: no copy (the running overlay is kept), and its alpha is still restored.
    const throwing = {
      globalAlpha: 1,
      drawImage(): void {
        throw new Error("tainted");
      },
    };
    const kept = handOverTierFade<Pic>({ el: { pic: 1 }, opacity: 0.4, fading: true }, () => tierFadeCopy<Pic>({ pic: 0 }, throwing, W, H));
    expect(kept).toEqual({ kind: "kept", from: 0.4, rehold: false });
    expect(throwing.globalAlpha).toBe(1);
  });

  it("an opacity outside [0, 1] or not a number is never passed on as one", () => {
    for (const [given, want] of [[1.7, 1], [-0.2, 0], [Number.NaN, 1]] as const) {
      const draws: [Pic, number][] = [];
      handOverTierFade<Pic>({ el: { pic: 1 }, opacity: given, fading: true }, picCopy(0, draws));
      expect(draws[0]![1]).toBe(want);
    }
  });
});

/* ── The overlay's whole life, executed: `createTierFadeSlot` (R4-VR1-4, 2026-09-27) ───────────────
 *
 * The verifier disposed the running driver on the `kept` path — the overlay then stayed on screen for
 * ever — and every test stayed green, because the record's updates were inline in scene.ts and the
 * class model below ran a copy of them. The slot now owns them, and runs here over a page that records
 * what is mounted and at what opacity. */
function page() {
  const shown = new Map<Pic, number>();
  const log: string[] = [];
  return {
    shown,
    log,
    host: {
      mount(el: Pic): void {
        shown.set(el, 1);
        log.push(`mount ${el.pic}`);
      },
      unmount(el: Pic): void {
        shown.delete(el);
        log.push(`unmount ${el.pic}`);
      },
      write(el: Pic, opacity: number): void {
        if (shown.has(el)) shown.set(el, opacity);
      },
    },
  };
}

describe("R4-VR1-4: the tier-fade slot — mount, hand-over, hold, fade and removal, over a page it can see", () => {
  const F = 1000 / 60;
  /** Frames until the slot's overlay leaves (or `max`). */
  const fadeOut = (slot: ReturnType<typeof createTierFadeSlot<Pic>>, max = 200): number => {
    let n = 0;
    while (slot.state !== "none" && n < max) {
      slot.frame(F, false, true);
      n += 1;
    }
    return n;
  };

  it("a tier change with nothing up mounts the copy, held at 1; the new tier's frame starts its hold; the fade removes it at exactly 0", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    expect(slot.tierChange(picCopy(0.3), false).kind).toBe("new");
    expect([...p.shown.values()]).toEqual([1]);
    expect(slot.state).toBe("held");
    slot.frame(F, false, true); // a held overlay has no driver: nothing moves
    expect(slot.opacity).toBe(1);
    const hold = slot.presented(false)!;
    expect(hold.live).toBe(true);
    expect(slot.state).toBe("waiting");
    expect(slot.presented(false), "a hold already waiting is not handed out twice").toBeNull();
    hold.start();
    expect(slot.state).toBe("fading");
    expect(fadeOut(slot)).toBeLessThanOrEqual(18);
    expect(p.shown.size, "removed on the frame the fade reached exactly 0").toBe(0);
    expect(hold.live).toBe(false);
  });

  it("composed: the running overlay leaves in the same call the one showing its picture arrives, and its driver never writes again", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.tierChange(picCopy(0.9), false);
    slot.presented(false)!.start();
    for (let i = 0; i < 6; i += 1) slot.frame(F, false, true);
    const at = slot.opacity;
    const old = [...p.shown.keys()][0]!;
    const plan = slot.tierChange(picCopy(0.2), false);
    expect(plan.kind).toBe("composed");
    expect(p.log.slice(-2), "unmounted and mounted in one call").toEqual([`unmount 0.9`, `mount ${at * 0.9 + (1 - at) * 0.2}`]);
    expect(p.shown.has(old)).toBe(false);
    expect([...p.shown.values()]).toEqual([1]);
    expect(slot.state).toBe("held");
    slot.frame(F, false, true);
    expect(p.shown.has(old), "the old driver wrote nothing back").toBe(false);
  });

  it("kept (a copy that FAILED with a fade running): the SAME overlay fades on to 0 and leaves — never stuck, never cut", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.tierChange(picCopy(0.9), false);
    slot.presented(false)!.start();
    for (let i = 0; i < 5; i += 1) slot.frame(F, false, true);
    const before = slot.opacity;
    expect(slot.tierChange(() => null, false)).toEqual({ kind: "kept", from: before, rehold: false });
    expect(slot.state).toBe("fading");
    let prev = before;
    let frames = 0;
    while (slot.state !== "none" && frames < 60) {
      slot.frame(F, false, true);
      expect(prev - slot.opacity).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      prev = slot.opacity;
      frames += 1;
    }
    expect(slot.state, "the kept fade ran to its end").toBe("none");
    expect(p.shown.size).toBe(0);
  });

  it("deferred (a warm-up in progress with a fade running): nothing changes, the fade HOLDS while nothing new is presented, and the change is composed from that value once it can be copied", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.tierChange(picCopy(0.9), false);
    slot.presented(false)!.start();
    for (let i = 0; i < 6; i += 1) slot.frame(F, false, true);
    const v = slot.opacity;
    const logged = p.log.length;
    expect(slot.tierChange(picCopy(0), true)).toEqual({ kind: "deferred", from: v });
    expect(p.log.length, "nothing mounted or removed").toBe(logged);
    for (let i = 0; i < 5; i += 1) slot.frame(F, false, false);
    expect(slot.opacity, "held through the warm-up").toBe(v);
    const plan = slot.tierChange(picCopy(0.2), false);
    expect(plan).toMatchObject({ kind: "composed", from: v });
    expect([...p.shown.values()]).toEqual([1]);
  });

  it("kept + rehold (a HELD overlay during a warm-up): the same element waits for the new tier again, and the old hold is dead", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.tierChange(picCopy(0.9), false);
    const oldHold = slot.presented(false)!;
    expect(slot.tierChange(picCopy(0), true)).toEqual({ kind: "kept", from: 1, rehold: true });
    expect(oldHold.live).toBe(false);
    oldHold.start();
    expect(slot.state, "a dead hold starts nothing").toBe("held");
    expect(p.shown.size).toBe(1);
    const hold = slot.presented(false)!;
    hold.start();
    expect(fadeOut(slot)).toBeLessThanOrEqual(18);
    expect(p.shown.size).toBe(0);
  });

  it("reduced motion: a HELD overlay (exactly 1) mounted while motion was already reduced is swapped away on the new tier's frame (§4.8); a fading one is never swapped by `presented`", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.frame(F, true, true); // the scene's frames have been passing reduced = true since before the change
    slot.tierChange(picCopy(0.9), false);
    expect(slot.presented(true)).toBeNull();
    expect(p.shown.size).toBe(0);
    slot.tierChange(picCopy(0.9), false);
    slot.presented(false)!.start();
    slot.frame(F, false, true);
    expect(slot.presented(true)).toBeNull();
    expect(slot.state).toBe("fading");
  });

  /* R4-VR2-4 (verifier round 2 of R4): the class model exempted "a reduced-motion toggle landing while an overlay
     is held or waiting at exactly 1, including a composed overlay that carries a remnant of a fade already
     running", and the slot swapped such an overlay away in one frame. The owner's decision grants no exemption
     for a held overlay. The rule now: an overlay that was on screen under FULL motion when reduced motion turned
     on is finished at the cap like a mid-fade one; only an overlay mounted and held while motion was reduced
     throughout gets §4.8's swap at exactly 1. */
  const leavesAtCap = (slot: ReturnType<typeof createTierFadeSlot<Pic>>, p: ReturnType<typeof page>): number => {
    let prev = [...p.shown.values()].at(-1) ?? 0;
    let frames = 0;
    while (p.shown.size > 0 && frames < 40) {
      slot.frame(F, true, true);
      const now = [...p.shown.values()].at(-1) ?? 0;
      expect(prev - now, `frame ${frames}: one frame moved the overlay ${prev - now}`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      prev = now;
      frames += 1;
    }
    expect(p.shown.size, "the overlay leaves").toBe(0);
    return frames;
  };

  it("a reduced-motion toggle while an overlay is HELD at 1 finishes it at the cap, never swaps it", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.frame(F, false, true);
    slot.tierChange(picCopy(0.9), false);
    slot.frame(F, true, true); // the toggle lands while the overlay is held
    expect(slot.presented(true)).toBeNull();
    expect(p.shown.size, "the new tier's frame did not take the overlay down").toBe(1);
    expect(leavesAtCap(slot, p)).toBe(Math.ceil(1 / FADE_MAX_STEP - EPS));
  });

  it("a reduced-motion toggle while an overlay is WAITING on its hold finishes it at the cap once the hold starts", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.frame(F, false, true);
    slot.tierChange(picCopy(0.9), false);
    const hold = slot.presented(false)!;
    slot.frame(F, true, true); // the toggle lands while the hold waits
    expect(p.shown.size).toBe(1);
    hold.start();
    leavesAtCap(slot, p);
  });

  it("a COMPOSED overlay carrying a running fade's remnant, held when the toggle lands, is finished at the cap too", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.frame(F, false, true);
    slot.tierChange(picCopy(0.9), false);
    slot.presented(false)!.start();
    for (let i = 0; i < 5; i += 1) slot.frame(F, false, true);
    expect(slot.state).toBe("fading");
    expect(slot.tierChange(picCopy(0.2), false).kind).toBe("composed");
    slot.frame(F, true, true);
    expect(slot.presented(true)).toBeNull();
    expect(p.shown.size).toBe(1);
    leavesAtCap(slot, p);
  });

  it("dispose removes whatever is up (teardown with the canvas), and is final", () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.tierChange(picCopy(0.9), false);
    slot.dispose();
    expect(p.shown.size).toBe(0);
    expect(slot.state).toBe("none");
    slot.dispose();
  });
});

/* ── A slot method acts only ON the slot (P3C-V2-2, verifier of phase 3) ──────────────────────────────────────────
 *
 * scene.test.ts finds every call on the slot by its TYPE. The verifier went round it by copying the methods off it:
 * `const copy = { ...tierFade }; copy.dispose();` disposed a running half-faded overlay in one frame, because the
 * slot's methods closed over its state and `copy` neither holds nor carries DOM. A longer list of copy shapes (spread,
 * Object.assign, entries, getOwnPropertyDescriptors, for-in, ...) is the same defect. The slot is therefore built so
 * that NO copy of a method can act: its state is private to the instance and every method reads it through `this`,
 * so a method runs only with the slot itself as its receiver, and a method value taken off it, spread off it or
 * called on anything else throws before it touches the page. The only way to run one is then with the slot as the
 * receiver or as the `this` handed to call/apply/bind/Reflect, which is a call on, or an argument of, a value of the
 * slot's type: the sites scene.test.ts finds by type. Enumerated from the object itself, never from a list. */
describe("P3C-V2-2: a tier-fade slot method acts only on the slot itself", () => {
  /** A slot with a fade running at mid-value, and the page it is lent. */
  const running = () => {
    const p = page();
    const slot = createTierFadeSlot<Pic>(p.host);
    slot.tierChange(picCopy(0.9), false);
    slot.presented(false)!.start();
    for (let i = 0; i < 6; i += 1) slot.frame(1000 / 60, false, true);
    const at = slot.opacity;
    expect(at, "precondition: a fade is running, half-faded").toBeGreaterThan(0.05);
    expect(at).toBeLessThan(1);
    return { p, slot, at, before: [...p.log] };
  };

  it("carries no function-valued property of its own: a spread or copy of it takes no method with it", () => {
    const { slot } = running();
    const own = Object.getOwnPropertyNames(slot).filter((k) => typeof Object.getOwnPropertyDescriptor(slot, k)?.value === "function");
    expect(own, "an own function-valued member is copied by a spread and closes over the slot").toEqual([]);
    const copy: Record<string, unknown> = { ...slot };
    expect(Object.entries(copy).filter(([, v]) => typeof v === "function")).toEqual([]);
    expect(Object.entries(Object.assign({}, slot)).filter(([, v]) => typeof v === "function")).toEqual([]);
  });

  it("every method and accessor it has, taken off it and run on anything else, throws before touching the page", () => {
    const { p, slot, at, before } = running();
    const proto = Object.getPrototypeOf(slot) as object;
    const members = Object.getOwnPropertyNames(proto).filter((k) => k !== "constructor");
    const fns: [string, (...a: unknown[]) => unknown][] = [];
    for (const k of members) {
      const d = Object.getOwnPropertyDescriptor(proto, k)!;
      if (typeof d.value === "function") fns.push([k, d.value as (...a: unknown[]) => unknown]);
      if (d.get !== undefined) fns.push([`get ${k}`, d.get as () => unknown]);
    }
    // Not vacuous: the four operations scene.ts calls, and both readings, are among them.
    expect(fns.map(([k]) => k)).toEqual(expect.arrayContaining(["tierChange", "presented", "frame", "dispose", "get state", "get opacity"]));
    const others: [string, unknown][] = [
      ["undefined", undefined],
      ["a spread copy", { ...slot }],
      ["an object on its prototype", Object.create(proto) as unknown],
      ["a copy of its own properties", Object.defineProperties({}, Object.getOwnPropertyDescriptors(slot))],
    ];
    const args = [picCopy(0.1), false];
    for (const [k, fn] of fns) {
      for (const [what, self] of others) {
        expect(() => fn.apply(self, args), `${k} on ${what}`).toThrow(TypeError);
      }
    }
    expect(p.log, "nothing mounted, unmounted or re-mounted by any of those calls").toEqual(before);
    expect(slot.opacity, "the running fade was not moved").toBe(at);
    expect(slot.state).toBe("fading");
  });

  it("control: the same methods, run on the slot itself, do act", () => {
    const { p, slot } = running();
    const dispose = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(slot) as object, "dispose")!.value as () => void;
    dispose.call(slot);
    expect(p.shown.size).toBe(0);
    expect(slot.state).toBe("none");
  });
});

/* ── The class, executed: every path that touches a running overlay, through the slot, on a model of the screen ──
 *
 * One scalar per picture: the canvas shows `base` (the last composed frame), an overlay shows its own
 * `pic` at opacity α, so the screen is α·pic + (1 - α)·base. The overlay is `createTierFadeSlot` itself
 * (R4-VR1-4), over a page that records what is mounted; the scene's part — which jsdom cannot run (no
 * WebGL) — is followed step for step and pinned in scene.test.ts: `applyQuality` asks the slot first
 * and waits on `deferred` until the warm-up that deferred it has ended (`deferredQuality`), the new
 * tier's composed frame calls `presented`, the hold starts the fade some frames later, and `frame()`
 * drives the slot once per frame with `compiled` (false while a warm-up runs). It is driven through
 * seeded sequences of every path the owner named: a tier change mid-hold and mid-fade, during a warm-up
 * (a theme change, new data, another tier change) or with a copy that fails; a tab hidden for up to
 * 4 s and the tier change a returning tab lands on its first frame; host stalls; and the driver's
 * `reduced` flag turned on mid-fade (what scene.ts `setReducedMotion` passes it). The invariants:
 *   1. on every presented frame, what the OVERLAY changes on screen — over the canvas the previous
 *      frame showed — is at most FADE_MAX_STEP of the difference between its picture and that canvas
 *      (a change of the canvas itself is not the overlay's doing and is factored out; so is the
 *      reduced-motion swap of an overlay still at exactly 1, which is that contract);
 *   2. a new tier's first frame lands under at least the overlay that was up when the change was applied
 *      (asked for, or — deferred — when its deferral ended);
 *   3. (R4-VR1-5) it never lands under a PARTLY faded overlay, showing part of its pop, unless its copy
 *      failed outright — counted apart, the stated residual;
 *   4. (R4-VR1-4) at most one overlay is ever mounted, and once the events stop every overlay leaves.
 * The pre-fix wiring, the wiring that stepped a fade through the warm-up, and the wiring that did not
 * defer are run through the same model and must FAIL, so the model is known to see each defect. */
type ModelPolicy = "handover" | "pre-fix" | "step" | "no-defer";
function runOverlayModel(seed: number, policy: ModelPolicy) {
  let s = seed >>> 0;
  const rnd = (): number => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
  const p = page();
  let reduced = false;
  /* R4-VR2-4: §4.8's swap at exactly 1 is exempt from the cap only for an overlay that has been up under
     REDUCED motion throughout: mounted while reduced, carrying no remnant of an overlay that was not itself
     exempt (a `composed` overlay replaces the running one in the same task, and draws it in), and never
     shown under full motion since. An overlay on screen under full motion when reduced turns on is a toggle
     landing, and is held to the cap like any other path. Recorded at the mount, from the page's own events. */
  const reducedThroughout = new Map<Pic, boolean>();
  let justUnmounted: Pic | null = null;
  const slot = createTierFadeSlot<Pic>({
    mount(el: Pic): void {
      reducedThroughout.set(el, reduced && (justUnmounted === null || reducedThroughout.get(justUnmounted) === true));
      justUnmounted = null;
      p.host.mount(el);
    },
    unmount(el: Pic): void {
      justUnmounted = el;
      p.host.unmount(el);
    },
    write: p.host.write,
  });
  let base = rnd();
  let warmup = 0;
  let pendingBase: number | null = null;
  /* The tier change a warm-up is for (null: a theme change or new data), and the one deferred. */
  let tierWarm: { askAlpha: number; copyFailed: boolean } | null = null;
  let deferred = false;
  let hold: { handle: TierFadeHoldHandle; frames: number } | null = null;
  const r = { worst: 0, frames: 0, handovers: 0, deferrals: 0, landings: 0, landingShortfall: 0, partialLandings: 0, residualLandings: 0, maxMounted: 0, leftOver: 0, exemptSwaps: 0 };
  const top = (): { el: Pic; pic: number; alpha: number } | null => {
    let out: { el: Pic; pic: number; alpha: number } | null = null;
    for (const [el, alpha] of p.shown) out = { el, pic: el.pic, alpha };
    return out;
  };
  const exemptSwap = (was: { el: Pic; alpha: number } | null): boolean => was !== null && was.alpha === 1 && reducedThroughout.get(was.el) === true;
  const tierChange = (askAlpha: number): void => {
    const warming = warmup > 0;
    const fails = !warming && rnd() < 0.15; // a copy that fails outright (the kept-fading path, and its residual)
    const copy = warming || fails ? () => null : picCopy(base);
    let kind: string;
    if (policy === "pre-fix") {
      // snapshotForTierFade as it was: clearTierFade() first, then a copy of the canvas UNDER the overlay.
      slot.dispose();
      kind = slot.tierChange(copy, false).kind;
    } else kind = slot.tierChange(copy, policy === "no-defer" ? false : warming).kind;
    if (kind === "deferred") {
      r.deferrals += 1;
      deferred = true;
      return;
    }
    deferred = false;
    if (kind === "composed") r.handovers += 1;
    tierWarm = { askAlpha, copyFailed: kind === "kept" && fails && slot.state === "fading" };
    warmup = 1 + Math.floor(rnd() * 4);
    pendingBase = rnd();
  };
  /* The screen the previous frame presented (taken before this frame's events: a tier change between
     two frames is part of what the next presented frame shows). */
  let prev: { pic: number; alpha: number } | null = null;
  let prevBase = base;
  const step = (raw: number, events: boolean): void => {
    justUnmounted = null;
    if (events) {
      const e = rnd();
      if (e < 0.06) tierChange(slot.opacity);
      else if (e < 0.12) {
        // A theme change or new data: a warm-up of its own; the new picture lands when it ends.
        warmup = Math.max(warmup, 1 + Math.floor(rnd() * 4));
        pendingBase = rnd();
      } else if (e < 0.14) raw = 200 + rnd() * 3800; // a hidden tab: no frame for up to 4 s, then this one
      else if (e < 0.24) raw = 33 + rnd() * 220; // a host stall
      else if (e < 0.255) reduced = true;
      else if (e < 0.28) reduced = false;
    }
    // frame(): the slot first, with `compiled` (false while the warm-up runs; "step" is the wiring before R4-V1-4).
    slot.frame(raw, reduced, policy === "step" || warmup === 0);
    let swapped = false;
    if (deferred && warmup === 0) {
      /* The deferred tier change is applied on the first frame after the warm-up (and that frame
         renders nothing). The old tier presented meanwhile, so it is judged from what is up NOW. */
      tierChange(slot.opacity);
    } else if (warmup > 0) {
      warmup -= 1;
      if (warmup === 0 && pendingBase !== null) {
        // The warm-up ended: its first composed frame lands now, under whatever overlay is up.
        if (tierWarm !== null) {
          const alpha = slot.opacity;
          r.landings += 1;
          r.landingShortfall = Math.max(r.landingShortfall, tierWarm.askAlpha - alpha);
          if (alpha > 0 && alpha < 1) {
            if (tierWarm.copyFailed) r.residualLandings += 1;
            else r.partialLandings += 1;
          }
          tierWarm = null;
        }
        base = pendingBase;
        pendingBase = null;
        const was = top();
        const h = slot.presented(reduced);
        if (h !== null) hold = { handle: h, frames: Math.floor(rnd() * 4) };
        else if (exemptSwap(was) && top() === null) {
        swapped = true; // §4.8's swap at exactly 1
        r.exemptSwaps += 1;
      }
      }
    } else {
      const was = top();
      const h = slot.presented(reduced);
      if (h !== null) hold = { handle: h, frames: Math.floor(rnd() * 4) };
      else if (exemptSwap(was) && top() === null) {
        swapped = true; // §4.8's swap at exactly 1
        r.exemptSwaps += 1;
      }
      if (hold !== null && hold.handle.live && hold.frames-- <= 0) {
        hold.handle.start();
        hold = null;
      }
    }
    const now = top();
    if (!reduced) for (const el of reducedThroughout.keys()) reducedThroughout.set(el, false);
    for (const el of [...reducedThroughout.keys()]) if (!p.shown.has(el)) reducedThroughout.delete(el);
    if (prev !== null && !swapped) {
      const moved = Math.abs((now === null ? prevBase : now.alpha * now.pic + (1 - now.alpha) * prevBase) - (prev.alpha * prev.pic + (1 - prev.alpha) * prevBase));
      const span = Math.abs(prev.pic - prevBase);
      if (span > 1e-9) r.worst = Math.max(r.worst, moved / span);
    }
    r.maxMounted = Math.max(r.maxMounted, p.shown.size);
    r.frames += 1;
    prev = now;
    prevBase = base;
  };
  for (let i = 0; i < 400; i += 1) step(1000 / 60, true);
  // The events stop: every overlay must leave (a stuck one is a defect the cap cannot see).
  for (let i = 0; i < 150; i += 1) step(1000 / 60, false);
  r.leftOver = p.shown.size;
  return r;
}

describe("C5-R2-1 as a class: no path removes, replaces or resets a running overlay faster than the per-frame cap", () => {
  const SEEDS = Array.from({ length: 40 }, (_, i) => 0xc5 + i * 7919);
  const runs = SEEDS.map((seed) => ({ seed, r: runOverlayModel(seed, "handover") }));

  it("the model sees the defect: the pre-fix wiring (clear first, then copy) cuts a half-faded overlay", () => {
    const cut = SEEDS.map((seed) => runOverlayModel(seed, "pre-fix")).filter((r) => r.worst > FADE_MAX_STEP + EPS);
    expect(cut.length, "the pre-fix wiring passed the invariant: the model cannot see the cut").toBeGreaterThan(0);
  });

  it("the slot never moves the screen by more than FADE_MAX_STEP of the overlay's contrast in one frame, on any seeded path", () => {
    let handovers = 0;
    for (const { seed, r } of runs) {
      expect(r.worst, `seed ${seed}: one frame moved ${r.worst.toFixed(3)} of the overlay's contrast`).toBeLessThanOrEqual(FADE_MAX_STEP + EPS);
      expect(r.frames).toBe(550);
      handovers += r.handovers;
    }
    // Not vacuous: running overlays were actually handed over, many times.
    expect(handovers).toBeGreaterThan(20);
    /* ...and §4.8's exempt swap (an overlay up under reduced motion throughout) is actually taken, so the
       exemption is exercised rather than merely declared (R4-VR2-4). */
    expect(runs.reduce((n, x) => n + x.r.exemptSwaps, 0)).toBeGreaterThan(0);
  });

  it("a new tier's first frame always lands under at least the overlay that was on screen when the change was asked for (the fade holds while nothing new is presented)", () => {
    /* R4-V1-4 (verifier, 2026-09-27): a fade that ran on through a warm-up could reach 0 and leave
       first: the new tier's pop then landed with no overlay — up to the whole pop. */
    let landings = 0;
    for (const { seed, r } of runs) {
      expect(r.landingShortfall, `seed ${seed}: a new tier landed under ${r.landingShortfall.toFixed(3)} less overlay than was up at the change`).toBeLessThanOrEqual(1e-12);
      landings += r.landings;
    }
    expect(landings, "not vacuous: new tiers landed").toBeGreaterThan(40);
    const short = SEEDS.map((seed) => runOverlayModel(seed, "step")).filter((r) => r.landingShortfall > 0.05);
    expect(short.length, "the stepping wiring passed: the model cannot see a fade ending inside the warm-up").toBeGreaterThan(0);
  });

  it("R4-VR1-5: a new tier's first frame never lands under a PARTLY faded overlay — a tier change during a warm-up with a fade running is deferred and handed over — except where the copy failed outright", () => {
    let deferrals = 0;
    for (const { seed, r } of runs) {
      expect(r.partialLandings, `seed ${seed}: ${r.partialLandings} new tier(s) landed under a partly faded overlay`).toBe(0);
      deferrals += r.deferrals;
    }
    expect(deferrals, "not vacuous: tier changes were asked for during a warm-up with a fade running").toBeGreaterThan(5);
    // ...and the model sees the defect: the wiring that did not defer lands tiers under a partial fade.
    const partial = SEEDS.map((seed) => runOverlayModel(seed, "no-defer")).filter((r) => r.partialLandings > 0);
    expect(partial.length, "the non-deferring wiring passed: the model cannot see a tier landing under a partial fade").toBeGreaterThan(0);
  });

  it("R4-VR1-4: at most one overlay is ever mounted, and once the events stop every overlay leaves (none is left stuck)", () => {
    for (const { seed, r } of runs) {
      expect(r.maxMounted, `seed ${seed}`).toBeLessThanOrEqual(1);
      expect(r.leftOver, `seed ${seed}: an overlay is still up 150 quiet frames after the last event`).toBe(0);
    }
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

describe("the emphasis subjects are the loaded fabric's own (P3C-V2-3)", () => {
  it("FOCUS is a real hub and SECOND one of its neighbours, so a focus recedes a real neighbourhood", () => {
    expect(devices.some((d) => d.id === FOCUS)).toBe(true);
    expect(neighboursOf(FOCUS).size).toBeGreaterThan(1);
    expect(neighboursOf(FOCUS).has(SECOND)).toBe(true);
  });
});
