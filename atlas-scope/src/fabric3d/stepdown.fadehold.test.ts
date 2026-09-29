/**
 * stepdown.fadehold.test.ts — how long a tier change may hold the OLD tier's picture over the canvas.
 *
 * MEASURED by the 2026-09-23 grading (C5 (b)), light/high orbit on a contended host: the automatic
 * step-down landed mid-orbit, and the overlay held opacity 1 for about 1,000 ms (700 ms at
 * high -> balanced) while 126 of 282 moving frames changed nothing on screen — the orbit visibly
 * stopped — then released with a 6.08x one-frame change. The hold waited for three frames under
 * 40 ms, which a busy host does not produce, so only the 1,200 ms backstop ended it; and the picture
 * it held was a view the camera had already left.
 *
 * The rule pinned here (`createTierFadeHold`): the overlay holds only while the frames underneath are
 * the SAME view of the SAME content as the frame it was taken from. The first frame on which the
 * camera moved or the content changed starts the fade — the new tier's frame is then the one
 * presenting motion, and the cross-fade is the only thing between them. A still view keeps the calm
 * wait (the step-up case it was built for), bounded by `maxHoldMs`, the figure design-brief.md §4.8
 * states (src/core/motion-inventory.test.ts holds the row to it).
 */
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";
import { TIER_FADE_HOLD_DEFAULTS, createTierFadeHold } from "./stepdown";
import { easeFraction } from "./emphasis";

/** Frames after the new tier's first presented one (t = 0): returns the hold, in ms, and in frames. */
function holdOf(frames: readonly { ms: number; changed: boolean }[]): { ms: number; frames: number } | null {
  const hold = createTierFadeHold(0);
  let t = 0;
  for (let i = 0; i < frames.length; i += 1) {
    const f = frames[i]!;
    t += f.ms;
    if (hold.frame(t, f.ms, f.changed)) return { ms: t, frames: i + 1 };
  }
  return null;
}

/** The contended host's orbit: 45-60 ms frames, the camera moving on every one. */
const busyOrbit = Array.from({ length: 60 }, (_, i) => ({ ms: 45 + (i % 4) * 5, changed: true }));

describe("the tier cross-fade never holds a view the camera has left (C5 (b))", () => {
  it("an orbit in progress starts the fade on the first frame after the new tier presents", () => {
    const h = holdOf(busyOrbit);
    expect(h, "the hold never ended").not.toBeNull();
    expect(h!.frames, `held ${h!.ms} ms over a moving camera`).toBe(1);
  });

  it("a content change under a still camera releases it the same way (an ease, a selection, a trace)", () => {
    const frames = [{ ms: 16.7, changed: false }, { ms: 48, changed: true }, ...Array.from({ length: 80 }, () => ({ ms: 50, changed: false }))];
    expect(holdOf(frames)?.frames).toBe(2);
  });

  it("a still view keeps the calm wait the step-up needs: a heavy first-use frame does not start it", () => {
    /* The measured low -> high case: one 210 ms frame of program links, then ordinary frames. */
    const frames = [{ ms: 210, changed: false }, ...Array.from({ length: 10 }, () => ({ ms: 16.7, changed: false }))];
    expect(holdOf(frames)?.frames).toBe(1 + TIER_FADE_HOLD_DEFAULTS.calmFrames);
  });

  it("a still view on a host that never presents a calm frame is held no longer than the stated bound", () => {
    const frames = Array.from({ length: 200 }, () => ({ ms: 50, changed: false }));
    const h = holdOf(frames)!;
    expect(h.ms).toBeGreaterThanOrEqual(TIER_FADE_HOLD_DEFAULTS.maxHoldMs);
    expect(h.ms - 50).toBeLessThan(TIER_FADE_HOLD_DEFAULTS.maxHoldMs);
  });
});

/* ── The harness that grades the fade (review/capture-motion.mjs), known answers both ways ─────────
 *
 * The hold above decides WHEN the fade starts; the per-frame bound is `stepTierFade` (emphasis.ts,
 * emphasis.test.ts). What the grader then MEASURES is capture-motion.mjs's `analyseFade` and the
 * verdict it feeds, and those are pinned here on the recorded failure itself (report.json at 7f67013,
 * dark/tier-fade-high-to-low-r3-nocopy) so the gate is known to fail on what it failed on, to fail
 * above the product's 0.2 cap rather than only above 0.25, and to publish no composite share it did
 * not judge (the grading printed a 41.1 "share" of a zero change for every light fade). */
interface FadeFrame {
  i: number;
  ts: number;
  quality: string;
  framesTimed: number;
  fade: { opacity: number; transition: string } | null;
}
interface FadeAnalysis {
  established: boolean;
  maxOpacityStep: number;
  maxOpacityStepRaw: number;
  maxOpacityStepFrame: number;
  fadeMs: number;
  compositeJudged: boolean;
  compositeWhy: string;
  compositeMaxOneFrameShare: number | null;
  compositeMaskedMaxShare: number | null;
  compositeChangedPixels: number | null;
  hostStallFrames?: { frame: number; dtMs: number }[];
  stallExtended?: boolean;
  stalledAtFrame?: number | null;
  stallDtMs?: number | null;
}
interface Harness {
  T: { FADE_MAX_STEP: number; FADE_MAX_PIXEL_SHARE: number; FADE_MAX_MS: number; FADE_STALL_MS: number; FADE_HOST_STALL_MS: number };
  analyseFade: (seq: { id: string }, meta: FadeFrame[], L: Uint8Array[], w: number, h: number) => FadeAnalysis;
  fadeFailures: (tag: string, f: FadeAnalysis) => string[];
  stalledFadeVerdict: (tag: string, f: FadeAnalysis) => { established: boolean; why: string; fails: string[] };
}
const harness = async (): Promise<Harness> =>
  (await import(/* @vite-ignore */ pathToFileURL(resolve(process.cwd(), "review", "capture-motion.mjs")).href)) as Harness;

/** Frames 0..n at the given times; the overlay's opacity where given (null = no overlay). */
function trace(points: readonly (readonly [number, number | null])[]): FadeFrame[] {
  return points.map(([ts, op], i) => ({ i, ts, quality: "low", framesTimed: i, fade: op === null ? null : { opacity: op, transition: "" } }));
}
/** The recorded failure: 16.7 ms frames, the overlay from frame 20, the new chain's 116.7 ms frame,
 *  three calm frames, then 83.3 ms and 116.6 ms host frames — and the 0.36 cut. */
const GRADED: (readonly [number, number | null])[] = [
  ...Array.from({ length: 20 }, (_, i) => [i * 16.7, null] as const),
  ...Array.from({ length: 9 }, (_, i) => [(20 + i) * 16.7, 1] as const),
  [266.7, 1],
  [283.4, 1],
  [300.1, 1],
  [316.7, 1],
  [400, 1],
  [516.6, 0.64],
  [550, 0.44],
  [566.6, 0.34],
  [583.3, 0.25],
  [600, 0.17],
  [616.7, 0.11],
  [633.3, 0.06],
  [650, null],
  [666.7, null],
];

describe("capture-motion.mjs grades the tier fade against the per-frame cap, and says what it did not judge", () => {
  it("the recorded failure fails for the recorded reason: 0.36 in one frame", async () => {
    const { analyseFade, fadeFailures } = await harness();
    const f = analyseFade({ id: "tier-fade-high-to-low" }, trace(GRADED), [], 760, 790);
    expect(f.established).toBe(true);
    expect(f.maxOpacityStep).toBe(0.36);
    expect(fadeFailures("tier-fade-high-to-low-r3-nocopy", f).join("\n")).toMatch(/opacity fell 0\.36 in one frame/);
  });

  it("the bar is the product's cap, 0.2, stated by the harness itself — a 0.22 step fails, an exact 0.2 staircase passes", async () => {
    const { T, analyseFade, fadeFailures } = await harness();
    expect(T.FADE_MAX_STEP).toBe(0.2);
    const staircase = (steps: readonly number[]): FadeFrame[] => {
      const pts: [number, number | null][] = Array.from({ length: 10 }, (_, i) => [i * 16.7, 1]);
      let op = 1;
      let t = 9 * 16.7;
      for (const s of steps) {
        op = Math.max(0, op - s);
        t += 60;
        pts.push([t, op === 0 ? null : op]);
      }
      pts.push([t + 16.7, null]);
      return trace(pts);
    };
    const capped = analyseFade({ id: "x" }, staircase([0.2, 0.2, 0.2, 0.2, 0.2]), [], 10, 10);
    expect(fadeFailures("capped", capped).filter((m) => /opacity fell/.test(m))).toEqual([]);
    const over = analyseFade({ id: "x" }, staircase([0.22, 0.2, 0.2, 0.2, 0.18]), [], 10, 10);
    expect(fadeFailures("over", over).join("\n")).toMatch(/opacity fell 0\.22 in one frame/);
  });

  it("a fade judged without pixels publishes NO composite share and says why (the copy-off control)", async () => {
    const { analyseFade } = await harness();
    const f = analyseFade({ id: "tier-fade-high-to-low" }, trace(GRADED), [], 760, 790);
    expect(f.compositeJudged).toBe(false);
    expect(f.compositeMaxOneFrameShare).toBeNull();
    expect(f.compositeMaskedMaxShare).toBeNull();
    expect(f.compositeWhy).toMatch(/no pixels/);
  });

  it("two tiers that differ in almost no pixels are 'composite not applicable', with the count — not a silent share", async () => {
    const { analyseFade } = await harness();
    const meta = trace(GRADED);
    const w = 20;
    const h = 20;
    // One pixel differs between the old tier's picture and the new one.
    const L = meta.map((_, k) => {
      const a = new Uint8Array(w * h).fill(100);
      if (k >= 34) a[7] = 180;
      return a;
    });
    const f = analyseFade({ id: "tier-fade-high-to-low" }, meta, L, w, h);
    expect(f.compositeJudged).toBe(false);
    expect(f.compositeChangedPixels).toBe(1);
    expect(f.compositeMaxOneFrameShare).toBeNull();
    expect(f.compositeWhy).toMatch(/tiers differ in 1 px/);
  });

  it("the progress log never prints 'undefinedms': a drop prints its camera move, a restore its delay", async () => {
    /* The 2026-09-26 grading read "drop@34 undefinedms" (an AO drop in dark/high orbit-drag) next to
       the tier fade's frame 34 — a coincidence the one-template log made look like evidence. */
    const { aoLogEntry } = (await harness()) as Harness & { aoLogEntry: (x: object) => string };
    const jump = { shareOver8: 0.0012 };
    expect(aoLogEntry({ kind: "drop", frame: 34, camPx: 1.03, maskedByMotion: true, jump })).toBe("drop@34 cam 1.03px masked 0.0012");
    expect(aoLogEntry({ kind: "restore", frame: 51, msAfterLastCameraChange: 150.1, jump })).toBe("restore@51 150.1ms 0.0012");
    expect(aoLogEntry({ kind: "drop", frame: 9, camPx: 0.2, maskedByMotion: false, jump })).not.toMatch(/undefined/);
  });

  it("a real change carried by one frame fails on the MASKED share (area alone does not dilute a share: the whole-canvas one fails it too; see the drift case below)", async () => {
    const { T, analyseFade, fadeFailures } = await harness();
    const meta = trace(GRADED);
    const w = 40;
    const h = 40;
    // 400 of 1,600 px change by 60/255 — all of it on frame 34 (a cut the opacity trace also shows).
    const L = meta.map((_, k) => {
      const a = new Uint8Array(w * h).fill(100);
      if (k >= 34) for (let p = 0; p < 400; p += 1) a[p] = 160;
      return a;
    });
    const f = analyseFade({ id: "tier-fade-high-to-low" }, meta, L, w, h);
    expect(f.compositeJudged).toBe(true);
    expect(f.compositeChangedPixels).toBe(400);
    expect(f.compositeMaskedMaxShare).toBe(1);
    expect(fadeFailures("cut", f).join("\n")).toMatch(new RegExp(`masked .*bar ${T.FADE_MAX_PIXEL_SHARE}`));
  });
});

/* ── The C5 step bar and the C6 duration bar, where a host stall makes them collide ─────────────────
 *
 * Independent verification (2026-09-26, fresh build, contended host) failed 2 of 24 fades on the
 * 300 ms DURATION bar although every step was within the 0.2 cap. dark/tier-fade-low-to-high-r2-copy
 * ran 16.7 ms frames down to 0.25 at t = 883.3, then one 83.3 ms frame (0.25 -> 0.05, the cap
 * binding) and one 50 ms frame to removal at 1016.6: 316.6 ms. A duration measured on the wall clock
 * is the HOST's as much as the product's. By the offline model (capture-motion.mjs T, the tier
 * cross-fade note), one 50 ms frame among the last frames takes even an UNCAPPED wall-clock fade to
 * 300 ms. So the 300 ms bar judges the PRODUCT's duration only on fades the host presented
 * ordinarily. A fade with a host stall inside it may pass 300 ms only if every frame after the bar
 * either ends the fade or moves the full cap: a stalled fade catching up, never one that dawdles. */
const E = (t: number): number => easeFraction("ease-in-out", t);
/** Overlay from frame 4; the fade leaves 1 after frame 11 and runs eleven 16.7 ms frames of a
 *  `durationMs` ease-in-out, then `tail` ([frame interval, opacity]), then one frame without it. */
function stalledTrace(tail: (before: number) => readonly (readonly [number, number | null])[], durationMs = 280): FadeFrame[] {
  const pts: [number, number | null][] = Array.from({ length: 12 }, (_, i) => [i * 16.7, i < 4 ? null : 1]);
  const t0 = 11 * 16.7;
  for (let k = 1; k <= 11; k += 1) pts.push([t0 + k * 16.7, 1 - E((k * 16.7) / durationMs)]);
  const before = pts[pts.length - 1]![1]!;
  for (const [dt, op] of tail(before)) pts.push([Math.round((pts[pts.length - 1]![0] + dt) * 10) / 10, op]);
  pts.push([pts[pts.length - 1]![0] + 16.7, null]);
  return trace(pts);
}
/** The verifier's r2-copy shape: an 83.3 ms frame on which the cap binds (-0.2), then a 50 ms frame to removal. */
const R2_COPY = (before: number) => [[83.3, before - 0.2], [50, null]] as const;
/** The same stall, then a product that DAWDLES past the bar: 0.02 on a 50 ms frame instead of the cap or the end. */
const DAWDLE = (before: number) => [[83.3, before - 0.2], [50, before - 0.22], [16.7, null]] as const;

describe("capture-motion.mjs: the 300 ms bar judges the product's duration, and a host stall may only delay a fade at the full cap", () => {
  it("the verifier's r2-copy shape (83.3 ms then 50 ms host frames, the cap binding) is a stall-extended fade, not a duration failure", async () => {
    const { T, analyseFade, fadeFailures } = await harness();
    const f = analyseFade({ id: "tier-fade-low-to-high" }, stalledTrace(R2_COPY), [], 10, 10);
    expect(f.established).toBe(true);
    expect(f.fadeMs).toBeGreaterThanOrEqual(T.FADE_MAX_MS);
    expect(f.maxOpacityStepRaw).toBeLessThanOrEqual(T.FADE_MAX_STEP + 1e-9);
    expect(f.stallExtended, "the fade is reported as stall-extended").toBe(true);
    expect((f.hostStallFrames ?? []).map((s) => s.dtMs)).toEqual([83.3, 50]);
    expect(fadeFailures("dark/tier-fade-low-to-high-r2-copy", f)).toEqual([]);
  });

  it("a stall-extended fade that DAWDLES past the bar fails: every frame after 300 ms must end it or move the full cap", async () => {
    const { analyseFade, fadeFailures } = await harness();
    const f = analyseFade({ id: "tier-fade-low-to-high" }, stalledTrace(DAWDLE), [], 10, 10);
    expect(f.stallExtended).toBe(true);
    expect(fadeFailures("dawdle", f).join("\n")).toMatch(/dawdle: fade lasted [\d.]+ ms, extended by a host stall .*moved only 0\.02/);
  });

  it("a fade over 300 ms on ordinary frames is the product's own duration: it fails, whatever it steps", async () => {
    const { T, analyseFade, fadeFailures } = await harness();
    // A 340 ms ease-in-out on steady 16.7 ms frames: no host stall, every step small.
    const pts: [number, number | null][] = Array.from({ length: 12 }, (_, i) => [i * 16.7, i < 4 ? null : 1]);
    for (let k = 1; k <= 30; k += 1) {
      const v = 1 - E((k * 16.7) / 340);
      pts.push([11 * 16.7 + k * 16.7, v <= 0 ? null : v]);
      if (v <= 0) break;
    }
    const slow = analyseFade({ id: "slow" }, trace(pts), [], 10, 10);
    expect(slow.fadeMs).toBeGreaterThanOrEqual(T.FADE_MAX_MS);
    expect(slow.maxOpacityStepRaw).toBeLessThan(T.FADE_MAX_STEP);
    expect(slow.hostStallFrames).toEqual([]);
    expect(slow.stallExtended).toBe(false);
    expect(fadeFailures("slow", slow).join("\n")).toMatch(/slow: fade lasted [\d.]+ ms \(bar: at least \d+, under 300; no host stall inside it\)/);
  });

  it("the stalled variant is established only when the injected stall produced a long frame (never vacuously)", async () => {
    const { T, analyseFade, stalledFadeVerdict } = await harness();
    const f = analyseFade({ id: "tier-fade-high-to-low" }, stalledTrace(R2_COPY), [], 10, 10);
    const landed = stalledFadeVerdict("dark/tier-fade-high-to-low-stalled", { ...f, stalledAtFrame: 12, stallDtMs: T.FADE_STALL_MS - 3.3 });
    expect(landed.established, landed.why).toBe(true);
    expect(landed.fails).toEqual([]);
    const idle = stalledFadeVerdict("dark/tier-fade-high-to-low-stalled", { ...f, stalledAtFrame: 12, stallDtMs: 16.7 });
    expect(idle.established).toBe(false);
    expect(idle.why).toMatch(/16\.7 ms.*no stall/);
    const never = stalledFadeVerdict("dark/tier-fade-high-to-low-stalled", { ...f, stalledAtFrame: null, stallDtMs: null });
    expect(never.established).toBe(false);
    expect(never.why).toMatch(/never injected/);
  });

  it("the stalled variant is held to the duration rule too: a stall may delay the fade, never let it dawdle", async () => {
    const { T, analyseFade, stalledFadeVerdict } = await harness();
    const f = analyseFade({ id: "tier-fade-high-to-low" }, stalledTrace(DAWDLE), [], 10, 10);
    const v = stalledFadeVerdict("dark/tier-fade-high-to-low-stalled", { ...f, stalledAtFrame: 12, stallDtMs: T.FADE_STALL_MS });
    expect(v.established).toBe(true);
    expect(v.fails.join("\n")).toMatch(/moved only 0\.02/);
  });

  it("a host stall is any frame that missed a 60 Hz vsync, a bar the harness states itself", async () => {
    const { T } = await harness();
    expect(T.FADE_HOST_STALL_MS).toBeGreaterThan(1000 / 60);
    expect(T.FADE_HOST_STALL_MS).toBeLessThan(2 * (1000 / 60));
  });
});

describe("capture-motion.mjs: the masked share catches a cut the whole-canvas share cannot", () => {
  it("sub-8/255 drift over most of the canvas dilutes the whole-canvas share under the bar; the masked share still fails the cut", async () => {
    const { T, analyseFade, fadeFailures } = await harness();
    const meta = trace(GRADED);
    const w = 40;
    const h = 40;
    // 100 px change by 60/255, all on frame 34 (a cut). The other 1,500 px drift 7/255 in 1/255 steps
    // over frames 35-41: a gradual change under FADE_MASK_DELTA, which carries most of the
    // whole-canvas total and so dilutes the one-frame whole-canvas share.
    const L = meta.map((_, k) => {
      const a = new Uint8Array(w * h).fill(100);
      if (k >= 34) for (let p = 0; p < 100; p += 1) a[p] = 160;
      const drift = Math.max(0, Math.min(7, k - 34));
      for (let p = 100; p < w * h; p += 1) a[p] = 100 + drift;
      return a;
    });
    const f = analyseFade({ id: "tier-fade-high-to-low" }, meta, L, w, h);
    expect(f.compositeJudged).toBe(true);
    expect(f.compositeChangedPixels).toBe(100);
    // The whole-canvas share passes: the drift carries most of the whole-canvas total...
    expect(f.compositeMaxOneFrameShare!).toBeLessThanOrEqual(T.FADE_MAX_PIXEL_SHARE);
    const fails = fadeFailures("cut", f);
    expect(fails.filter((m) => /of the composited change/.test(m))).toEqual([]);
    // ...and the masked share fails the cut.
    expect(f.compositeMaskedMaxShare).toBe(1);
    expect(fails.join("\n")).toMatch(new RegExp(`masked .*bar ${T.FADE_MAX_PIXEL_SHARE}`));
  });
});

/* ── C5-R2-2: the step bar is judged at FULL precision plus FADE_STEP_EPS, never on the rounded figure ─
 *
 * Verifier round 2 mutated the verdict to judge the PRINTED (2-decimal) step with a looser tolerance
 * (`maxOpacityStep > FADE_MAX_STEP + 0.015`) and every known answer above stayed green: they used only
 * 0.2 (passes) and 0.22 (fails), so a 0.2005-0.2149 step was never exercised. These pin the rule itself,
 * both ways, at the tolerance's own scale — including a step that PRINTS as 0.2 and must still fail. */
function stepTrace(steps: readonly number[], frameMs = 16.7): FadeFrame[] {
  const pts: [number, number | null][] = Array.from({ length: 10 }, (_, i) => [i * 16.7, 1]);
  let op = 1;
  let t = 9 * 16.7;
  for (const s of steps) {
    op -= s;
    t += frameMs;
    pts.push([t, op <= 0 ? null : op]);
  }
  pts.push([t + 16.7, null]);
  return trace(pts);
}

describe("capture-motion.mjs judges one frame's step on the full-precision opacity plus FADE_STEP_EPS (C5-R2-2)", () => {
  it("a step of FADE_MAX_STEP + 2 x FADE_STEP_EPS fails though it prints as 0.2; FADE_MAX_STEP + FADE_STEP_EPS / 2 passes", async () => {
    const { T, analyseFade, fadeFailures } = (await harness()) as Harness & { T: { FADE_STEP_EPS: number } };
    const E = T.FADE_STEP_EPS;
    expect(E).toBeGreaterThan(0);
    expect(E).toBeLessThan(0.005);
    const over = analyseFade({ id: "x" }, stepTrace([T.FADE_MAX_STEP + 2 * E, 0.2, 0.2, 0.2]), [], 10, 10);
    expect(over.maxOpacityStep, "the printed figure rounds to the bar").toBe(T.FADE_MAX_STEP);
    expect(fadeFailures("over", over).filter((m) => /opacity fell/.test(m)).join("\n")).toMatch(/over: opacity fell 0\.2 in one frame/);
    const within = analyseFade({ id: "x" }, stepTrace([T.FADE_MAX_STEP + E / 2, 0.2, 0.2, 0.2]), [], 10, 10);
    expect(within.maxOpacityStepRaw).toBeGreaterThan(T.FADE_MAX_STEP);
    expect(fadeFailures("within", within).filter((m) => /opacity fell/.test(m))).toEqual([]);
  });

  it("the catch-up rule the same way: past 300 ms a stalled fade's step of FADE_MAX_STEP - 2 x FADE_STEP_EPS (prints 0.2) is dawdling; - FADE_STEP_EPS / 2 is the cap", async () => {
    const { T, analyseFade, fadeFailures } = (await harness()) as Harness & { T: { FADE_STEP_EPS: number } };
    const E = T.FADE_STEP_EPS;
    /* 16.7 ms frames, one 100 ms host stall early (0.2), 0.03 steps to 0.45 at 283.7 ms, then the frame
       at 300.4 ms steps `x`, the next the full 0.2, and the one after ends the fade. */
    const catchUp = (x: number): FadeFrame[] => {
      const pts: [number, number | null][] = Array.from({ length: 12 }, (_, i) => [i * 16.7, i < 4 ? null : 1]);
      let t = 11 * 16.7;
      let op = 1;
      const push = (dt: number, s: number | null): void => {
        t = Math.round((t + dt) * 10) / 10;
        op = s === null ? 0 : op - s;
        pts.push([t, s === null ? null : op]);
      };
      push(16.7, 0.05);
      push(100, 0.2);
      for (let k = 0; k < 10; k += 1) push(16.7, 0.03);
      push(16.7, x);
      push(16.7, 0.2);
      push(16.7, null);
      return trace(pts);
    };
    const dawdle = analyseFade({ id: "x" }, catchUp(T.FADE_MAX_STEP - 2 * E), [], 10, 10);
    expect(dawdle.stallExtended).toBe(true);
    expect(fadeFailures("dawdle", dawdle).join("\n")).toMatch(/dawdle: fade lasted [\d.]+ ms, extended by a host stall .*moved only 0\.2 \(/);
    const cap = analyseFade({ id: "x" }, catchUp(T.FADE_MAX_STEP - E / 2), [], 10, 10);
    expect(cap.stallExtended).toBe(true);
    expect(fadeFailures("cap", cap)).toEqual([]);
  });
});

/* ── C5-R2-3: a recording that lost frames is never dense, and its fade is UNPROVEN ─────────────────
 *
 * Verifier round 2's run exited 4 on one fade that "never started in the recorded window": 63 frames
 * over 1,183 ms of a 2.5 s sequence, then nothing for ~1.3 s, and `density.ok` read TRUE because the
 * rules looked only at the frames that were recorded. Density is now judged against the recording
 * WINDOW (capture-motion.mjs T.MAX_EDGE_GAP_MS). */
interface Density {
  ok: boolean;
  why: string;
  lost: string[];
  tailGapMs: number | null;
}
interface RecordingWindow {
  startedAt: number;
  stoppedAt: number;
  skipped: number;
  hookErrors: number;
}
type FadeWithDensity = FadeAnalysis & { density: Density; why?: string };
interface HarnessR3 {
  T: { MAX_EDGE_GAP_MS: number };
  density: (meta: FadeFrame[], win?: RecordingWindow) => Density;
  fadeEvidence: (tag: string, f: FadeWithDensity, opts?: { stalled?: boolean }) => { established: boolean; why: string; fails: string[] };
  analyseFade: (seq: { id: string }, meta: FadeFrame[], L: Uint8Array[], w: number, h: number, win?: RecordingWindow) => FadeWithDensity;
}
const r3 = async (): Promise<HarnessR3> => (await harness()) as unknown as HarnessR3;
/** `n` frames of 16.7 ms from t = 0, the overlay at `op(i)`. */
const steady = (n: number, op: (i: number) => number | null = () => null): FadeFrame[] => trace(Array.from({ length: n }, (_, i) => [i * 16.7, op(i)] as const));

describe("capture-motion.mjs never records a sequence as dense when frames were lost (C5-R2-3)", () => {
  it("the verifier's shape — 63 frames over 1,183 ms of a 2,500 ms window, then nothing — is NOT dense, and says why", async () => {
    const { T, density } = await r3();
    const meta = trace(Array.from({ length: 63 }, (_, i) => [(i * 1183) / 62, 1] as const));
    const d = density(meta, { startedAt: 0, stoppedAt: 2500, skipped: 0, hookErrors: 0 });
    expect(d.ok).toBe(false);
    expect(d.tailGapMs).toBeGreaterThan(T.MAX_EDGE_GAP_MS);
    expect(d.why).toMatch(/no frame for the last 1317 ms of the recording/);
  });

  it("the same frames covering their window are dense; a frame the hook skipped, a hook error, or no window at all is not", async () => {
    const { density } = await r3();
    const meta = steady(150);
    const covered = { startedAt: -5, stoppedAt: 149 * 16.7 + 10, skipped: 0, hookErrors: 0 };
    expect(density(meta, covered).ok, density(meta, covered).why).toBe(true);
    expect(density(meta, { ...covered, skipped: 1 }).why).toMatch(/1 frame\(s\) the hook could not record/);
    expect(density(meta, { ...covered, hookErrors: 2 }).why).toMatch(/2 hook error/);
    expect(density(meta).ok, "without a window, lost edges cannot be ruled out").toBe(false);
    // A frameless HEAD is lost time too.
    expect(density(meta, { ...covered, startedAt: -400 }).why).toMatch(/no frame for the first 400 ms/);
  });

  it("a fade whose recording lost frames is UNPROVEN in its verdict — and a cut it did record still FAILS", async () => {
    const { analyseFade, fadeEvidence } = await r3();
    const win = (meta: FadeFrame[], tail: number): RecordingWindow => ({ startedAt: meta[0]!.ts - 5, stoppedAt: meta[meta.length - 1]!.ts + tail, skipped: 0, hookErrors: 0 });
    // A clean fade inside a covered window: evidence.
    const cleanMeta = steady(60, (i) => (i < 20 ? null : i < 25 ? 1 : i >= 41 ? null : Math.max(0.01, 1 - (i - 24) * 0.055)));
    const clean = analyseFade({ id: "tier-fade-high-to-low" }, cleanMeta, [], 10, 10, win(cleanMeta, 10));
    expect(clean.established).toBe(true);
    expect(fadeEvidence("clean", clean)).toEqual({ established: true, why: "", fails: [] });
    // The same fade, then 1.3 s with no frame before the recording stopped: not evidence.
    const lost = analyseFade({ id: "tier-fade-high-to-low" }, cleanMeta, [], 10, 10, win(cleanMeta, 1300));
    const ev = fadeEvidence("lost", lost);
    expect(ev.established).toBe(false);
    expect(ev.why).toMatch(/frames lost or too sparse: .*no frame for the last 1300 ms/);
    expect(ev.fails).toEqual([]);
    // The graded 0.36 cut in a recording that lost its tail: UNPROVEN as evidence of a pass, FAIL as a cut.
    const cutMeta = trace(GRADED);
    const cut = fadeEvidence("cut", analyseFade({ id: "tier-fade-high-to-low" }, cutMeta, [], 10, 10, win(cutMeta, 1300)));
    expect(cut.established).toBe(false);
    expect(cut.fails.join("\n")).toMatch(/opacity fell 0\.36 in one frame/);
    // The stalled item goes through the same gate before its own stall rule.
    const stalled = fadeEvidence("stalled", { ...lost, stalledAtFrame: 30, stallDtMs: 120 }, { stalled: true });
    expect(stalled.established).toBe(false);
    expect(stalled.why).toMatch(/frames lost/);
  });
});

/* ── C5-R2-1 in the browser: capture-motion.mjs's handover item, known answers both ways ────────────
 *
 * The hook measures, whenever the overlay on screen last frame leaves (replaced or removed) above
 * 0.005, how far the screen moved against how far a plain removal would move it (share, over the
 * pixels a removal would visibly change). `analyseHandover` turns the trace into the verdict. */
interface HFrame {
  i: number;
  ts: number;
  quality: string;
  framesTimed: number;
  fade: { opacity: number; transition: string; id: number } | null;
  handover: { kind: "replaced" | "removed"; fromOpacity: number; share: number | null; maskedPx: number; why?: string } | null;
}
interface Trig {
  below: number;
  hideMs: number;
  tier: string;
  firedAt: number | null;
  firedOpacity: number | null;
  returnedAt: number | null;
  appliedAt: number | null;
}
interface Handover {
  sequence?: string;
  established: boolean;
  notApplicable: boolean;
  why: string;
  events: { how: string }[];
  outcome: string | null;
  fails: string[];
  judgedEvents: number;
  returnStep: { frame: number; dtMs: number; step: number | null } | null;
}
const analyseHandover = async (meta: HFrame[], win: RecordingWindow, trig: Trig): Promise<Handover> =>
  ((await harness()) as unknown as { analyseHandover: (s: { id: string }, m: HFrame[], w: RecordingWindow, t: Trig) => Handover }).analyseHandover(
    { id: "tier-change-mid-fade" },
    meta,
    win,
    trig,
  );
/** A recorded handover sequence: overlay 1 appears at frame 12, holds 8 frames, fades 0.05 per frame
 *  until frame `at` (the tier change); from frame `at + 1`, `after` gives [overlay id, opacity] per
 *  frame (its first frame after `gapBefore` more ms), then 20 frames without an overlay. */
function handoverTrace(at: number, leave: HFrame["handover"], after: readonly (readonly [number, number])[], gapBefore = 0): HFrame[] {
  const f: HFrame[] = [];
  let t = 0;
  const push = (fade: HFrame["fade"], h: HFrame["handover"] = null, dt = 16.7): void => {
    t = Math.round((t + dt) * 10) / 10;
    f.push({ i: f.length, ts: t, quality: "low", framesTimed: f.length, fade, handover: h });
  };
  for (let i = 0; i < 12; i += 1) push(null);
  for (let i = 0; i < 8; i += 1) push({ opacity: 1, transition: "", id: 1 });
  for (let op = 0.95; f.length <= at; op -= 0.05) push({ opacity: Math.round(op * 100) / 100, transition: "", id: 1 });
  after.forEach(([id, op], k) => push({ opacity: op, transition: "", id }, k === 0 ? leave : null, k === 0 ? 16.7 + gapBefore : 16.7));
  for (let i = 0; i < 20; i += 1) push(null);
  return f;
}
/** One overlay fading from `from` by 0.1 per frame while above 0.005. */
const fadeFrom = (id: number, from: number): [number, number][] => {
  const out: [number, number][] = [];
  for (let v = from; v > 0.005; v = Math.round((v - 0.1) * 1000) / 1000) out.push([id, v]);
  return out;
};
const winOf = (m: HFrame[]): RecordingWindow => ({ startedAt: m[0]!.ts - 5, stoppedAt: m[m.length - 1]!.ts + 10, skipped: 0, hookErrors: 0 });
const trigAt = (at: number, opacity: number, hideMs = 0): Trig => ({ below: 0.6, hideMs, tier: "high", firedAt: hideMs ? at - 1 : at, firedOpacity: opacity, returnedAt: hideMs ? at : null, appliedAt: at });

describe("capture-motion.mjs: a running cross-fade must be handed over, never cut (C5-R2-1)", () => {
  it("a composed handover (the new overlay shows the screen: share ~0) that then fades by the cap PASSES", async () => {
    const at = 30;
    const meta = handoverTrace(at, { kind: "replaced", fromOpacity: 0.5, share: 0.004, maskedPx: 7800 }, [[2, 1], [2, 0.97], ...fadeFrom(2, 0.9)]);
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.5));
    expect(h.established, h.why).toBe(true);
    expect(h.outcome).toBe("replaced");
    expect(h.judgedEvents).toBe(1);
    expect(h.fails).toEqual([]);
  });

  it("the pre-fix product — cleared, then a copy of the canvas UNDER it (share 1) — FAILS on pixels", async () => {
    const at = 30;
    const meta = handoverTrace(at, { kind: "replaced", fromOpacity: 0.5, share: 1, maskedPx: 7800 }, [[2, 1], ...fadeFrom(2, 0.9)]);
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.5));
    expect(h.fails.join("\n")).toMatch(/the running overlay \(opacity 0\.5\) was replaced: the screen moved 1 of what removing it moves/);
  });

  it("a removal above the cap FAILS on its opacity even where the tiers differ in too few pixels to judge (the light theme)", async () => {
    const at = 30;
    const meta = handoverTrace(at, null, []);
    meta[at + 1]!.handover = { kind: "removed", fromOpacity: 0.5, share: 1, maskedPx: 4 };
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.5));
    expect(h.outcome).toBe("removed");
    expect(h.judgedEvents).toBe(0);
    expect(h.fails.join("\n")).toMatch(/removed at opacity 0\.5 \(a removal above 0\.2 is a cut, whatever the pixels\)/);
  });

  it("a replacement the tiers' pixels cannot judge is 'not applicable' — no pass is claimed from it, and none is failed", async () => {
    const at = 30;
    const meta = handoverTrace(at, { kind: "replaced", fromOpacity: 0.5, share: 0.9, maskedPx: 4 }, [[2, 1], ...fadeFrom(2, 0.9)]);
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.5));
    expect(h.judgedEvents).toBe(0);
    expect(h.fails).toEqual([]);
    /* R4-VR1-3 (verifier, 2026-09-27): this sequence used to count as ESTABLISHED — "6 of 6" in a run
       whose light-theme leaves were never judged. It is reported apart, never as a pass. */
    expect(h.established, "a sequence whose leave was never judged is not established").toBe(false);
    expect(h.notApplicable).toBe(true);
    expect(h.why).toMatch(/^not applicable: frame 31: replaced at opacity 0\.5, where a removal would change 4 px \(under \d+\)$/);
  });

  it("a leave the hook could NOT measure (the canvas resized, no screen before it) is UNPROVEN, not 'not applicable' — and not established", async () => {
    const at = 30;
    const meta = handoverTrace(at, { kind: "replaced", fromOpacity: 0.5, share: null, maskedPx: 0, why: "canvas resized" }, [[2, 1], ...fadeFrom(2, 0.9)]);
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.5));
    expect(h.established).toBe(false);
    expect(h.notApplicable).toBe(false);
    expect(h.why).toMatch(/frame 31: the overlay replaced at opacity 0\.5 was not judged \(canvas resized\)/);
    expect(h.fails).toEqual([]);
  });

  it("a removal at or under the cap is judged on its opacity (it moves the screen by exactly that share of a removal), wherever the pixels cannot show it", async () => {
    const at = 30;
    const meta = handoverTrace(at, null, []);
    meta[at + 1]!.handover = { kind: "removed", fromOpacity: 0.15, share: null, maskedPx: 0 };
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.15));
    expect(h.events.map((e) => e.how)).toEqual(["opacity"]);
    expect(h.established, h.why).toBe(true);
    expect(h.fails).toEqual([]);
  });

  it("the tier change KEPT the running overlay (no copy could be taken): the same element carries on, judged frame by frame", async () => {
    const at = 30;
    const meta = handoverTrace(at, null, fadeFrom(1, 0.4));
    const h = await analyseHandover(meta, winOf(meta), trigAt(at, 0.5));
    expect(h.established, h.why).toBe(true);
    expect(h.outcome).toBe("kept");
    expect(h.fails).toEqual([]);
  });

  it("the first frame back from a hidden tab is held to the cap: 0.2 passes, a larger jump of the same overlay fails", async () => {
    const at = 30;
    const good = handoverTrace(at, null, [[1, 0.25], ...fadeFrom(1, 0.15)], 2600);
    const g = await analyseHandover(good, winOf(good), trigAt(at + 1, 0.45, 2600));
    expect(g.returnStep).toMatchObject({ step: 0.2 });
    expect(g.returnStep!.dtMs).toBeGreaterThan(2600);
    expect(g.fails).toEqual([]);
    const jump = handoverTrace(at, null, [[1, 0.05]], 2600);
    const j = await analyseHandover(jump, winOf(jump), trigAt(at + 1, 0.45, 2600));
    expect(j.fails.join("\n")).toMatch(/one overlay's opacity moved 0\.4 in one frame \(a 2616\.7 ms frame; bar 0\.2\)/);
  });

  /* R4-VR2-2 (verifier round 2 of R4): C5-R2-2's rule — judge at FULL precision plus FADE_STEP_EPS, never the
     rounded figure — was pinned only at the analyseFade sites. analyseHandover judges with the same rule at two
     more: one overlay's step between frames, and a removal on its opacity. The known answers above used only
     0.4 and 0.5, so a regression to judging the rounded figure (0.2 + 2 x EPS prints as 0.2) with a looser
     tolerance passed them all. These straddle the bar by the EPS itself, both ways, at both sites. */
  it("one overlay's step is judged at full precision: FADE_MAX_STEP + 2 x FADE_STEP_EPS fails though it prints as 0.2; + FADE_STEP_EPS / 2 passes", async () => {
    const { T } = (await harness()) as Harness & { T: { FADE_STEP_EPS: number } };
    const E = T.FADE_STEP_EPS;
    const at = 30;
    const from = handoverTrace(at, null, [])[at]!.fade!.opacity;
    const stepTo = (s: number) => {
      const v = from - s;
      return handoverTrace(at, null, [[1, v], ...fadeFrom(1, Math.round((v - 0.1) * 1000) / 1000)]);
    };
    const over = stepTo(T.FADE_MAX_STEP + 2 * E);
    const o = await analyseHandover(over, winOf(over), trigAt(at, from));
    expect(o.fails.join("\n")).toMatch(/one overlay's opacity moved 0\.2 in one frame/);
    const within = stepTo(T.FADE_MAX_STEP + E / 2);
    const w = await analyseHandover(within, winOf(within), trigAt(at, from));
    expect(w.fails).toEqual([]);
  });

  it("a removal is judged on its full-precision opacity: FADE_MAX_STEP + 2 x FADE_STEP_EPS fails; + FADE_STEP_EPS / 2 is judged 'opacity' and passes", async () => {
    const { T } = (await harness()) as Harness & { T: { FADE_STEP_EPS: number } };
    const E = T.FADE_STEP_EPS;
    const at = 30;
    const removedAt = async (fromOpacity: number) => {
      const meta = handoverTrace(at, null, []);
      meta[at + 1]!.handover = { kind: "removed", fromOpacity, share: null, maskedPx: 0 };
      return analyseHandover(meta, winOf(meta), trigAt(at, fromOpacity));
    };
    const over = await removedAt(T.FADE_MAX_STEP + 2 * E);
    expect(over.fails.join("\n")).toMatch(/removed at opacity 0\.2 \(a removal above 0\.2 is a cut, whatever the pixels\)/);
    const within = await removedAt(T.FADE_MAX_STEP + E / 2);
    expect(within.events.map((e) => e.how)).toEqual(["opacity"]);
    expect(within.fails).toEqual([]);
    expect(within.established, within.why).toBe(true);
  });

  it("never established vacuously: a trigger that never fired, a tab that never returned, a fade still up at the end, or lost frames", async () => {
    const at = 30;
    const meta = handoverTrace(at, { kind: "replaced", fromOpacity: 0.5, share: 0.004, maskedPx: 7800 }, [[2, 1], ...fadeFrom(2, 0.9)]);
    const w = winOf(meta);
    expect((await analyseHandover(meta, w, { ...trigAt(at, 0.5), firedAt: null, appliedAt: null })).why).toMatch(/the trigger never fired/);
    expect((await analyseHandover(meta, w, { ...trigAt(at, 0.5, 2600), returnedAt: null, appliedAt: null })).why).toMatch(/hidden tab never returned/);
    const unfinished = meta.slice(0, at + 4);
    expect((await analyseHandover(unfinished, winOf(unfinished), trigAt(at, 0.5))).why).toMatch(/never finished/);
    const lost = await analyseHandover(meta, { ...w, stoppedAt: w.stoppedAt + 1300 }, trigAt(at, 0.5));
    expect(lost.established).toBe(false);
    expect(lost.why).toMatch(/frames lost/);
  });
});

/* ── The handover ITEM (R4-VR1-3): what the verdict may claim from the sequences ─────────────────── */
type ItemHv = { sequence: string; established: boolean; notApplicable: boolean; why: string; outcome: string; fails: string[]; events: { how: string }[] };
interface HandoverItem {
  fails: string[];
  established: boolean;
  why: string;
  judged: number;
  total: number;
}
const handoverItem = async (legs: { theme: string; tier: string; handovers?: ItemHv[] }[], problems: string[] = []): Promise<HandoverItem> =>
  (
    (await harness()) as unknown as {
      handoverItem: (l: typeof legs, themes: string[], ids: string[], p: string[]) => HandoverItem;
    }
  ).handoverItem(legs, ["dark", "light"], ["tier-change-mid-hold", "tier-change-mid-fade", "tier-change-tab-hidden"], problems);
const IDS = ["tier-change-mid-hold", "tier-change-mid-fade", "tier-change-tab-hidden"] as const;
const judgedHv = (id: string): ItemHv => ({ sequence: id, established: true, notApplicable: false, why: "", outcome: "replaced", fails: [], events: [{ how: "pixels" }] });
const naHv = (id: string): ItemHv => ({ sequence: id, established: false, notApplicable: true, why: "not applicable: frame 31: replaced at opacity 0.5, where a removal would change 0 px (under 64)", outcome: "replaced", fails: [], events: [{ how: "not applicable" }] });

describe("capture-motion.mjs: the handover item claims only what was judged (R4-VR1-3)", () => {
  it("every sequence judged in both themes: established, 'judged 6 of 6'", async () => {
    const legs = ["dark", "light"].map((theme) => ({ theme, tier: "high", handovers: IDS.map(judgedHv) }));
    const it6 = await handoverItem(legs);
    expect(it6.established, it6.why).toBe(true);
    expect(it6.why).toMatch(/^judged 6 of 6 handover sequences/);
  });

  it("the light theme's leaves not applicable, every sequence judged in the dark: established, and the count says 4 of 6 with the rest named", async () => {
    const legs = [
      { theme: "dark", tier: "high", handovers: IDS.map(judgedHv) },
      { theme: "light", tier: "high", handovers: [judgedHv(IDS[0]), naHv(IDS[1]), naHv(IDS[2])] },
    ];
    const r = await handoverItem(legs);
    expect(r.established, r.why).toBe(true);
    expect(r.judged).toBe(4);
    expect(r.why).toMatch(/^judged 4 of 6 handover sequences/);
    expect(r.why).toMatch(/not applicable \(no leave could show there\): light\/tier-change-mid-fade: not applicable: .*; light\/tier-change-tab-hidden: not applicable/);
  });

  it("a sequence judged in NO theme is not proven by the themes where nothing could show: UNPROVEN", async () => {
    const legs = [
      { theme: "dark", tier: "high", handovers: [judgedHv(IDS[0]), naHv(IDS[1]), judgedHv(IDS[2])] },
      { theme: "light", tier: "high", handovers: [judgedHv(IDS[0]), naHv(IDS[1]), naHv(IDS[2])] },
    ];
    const r = await handoverItem(legs);
    expect(r.established).toBe(false);
    expect(r.why).toMatch(/judged in no theme: tier-change-mid-fade/);
  });

  it("an unjudged leave, a sequence never recorded, or a leg problem is UNPROVEN; a recorded failure still fails", async () => {
    const unjudged: ItemHv = { ...judgedHv(IDS[1]), established: false, why: "frame 31: the overlay replaced at opacity 0.5 was not judged (canvas resized)", events: [{ how: "unjudged" }] };
    const a = await handoverItem([
      { theme: "dark", tier: "high", handovers: [judgedHv(IDS[0]), unjudged, judgedHv(IDS[2])] },
      { theme: "light", tier: "high", handovers: IDS.map(judgedHv) },
    ]);
    expect(a.established).toBe(false);
    expect(a.why).toMatch(/not established: dark\/tier-change-mid-fade: frame 31: .*canvas resized/);
    const b = await handoverItem([{ theme: "dark", tier: "high", handovers: IDS.map(judgedHv) }, { theme: "light", tier: "high", handovers: [judgedHv(IDS[0])] }]);
    expect(b.established).toBe(false);
    expect(b.why).toMatch(/light\/tier-change-mid-fade: not recorded/);
    const c = await handoverItem(["dark", "light"].map((theme) => ({ theme, tier: "high", handovers: IDS.map(judgedHv) })), ["dark/high: tier was balanced"]);
    expect(c.established).toBe(false);
    const cut = { ...judgedHv(IDS[1]), fails: ["tier-change-mid-fade: frame 31, the running overlay (opacity 0.5) was replaced: the screen moved 1 of what removing it moves"] };
    const d = await handoverItem([{ theme: "dark", tier: "high", handovers: [judgedHv(IDS[0]), cut, judgedHv(IDS[2])] }, { theme: "light", tier: "high", handovers: IDS.map(judgedHv) }]);
    expect(d.fails).toEqual([`dark/${cut.fails[0]}`]);
  });

  it("the handover legs are found by their recorded handovers, not by position: a leg without them contributes nothing", async () => {
    const legs = [
      { theme: "dark", tier: "low" },
      { theme: "dark", tier: "high", handovers: IDS.map(judgedHv) },
      { theme: "light", tier: "high", handovers: IDS.map(judgedHv) },
      { theme: "light", tier: "low" },
    ];
    expect((await handoverItem(legs)).established).toBe(true);
  });
});
