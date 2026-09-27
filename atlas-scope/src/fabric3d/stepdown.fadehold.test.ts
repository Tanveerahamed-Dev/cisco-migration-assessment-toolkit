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
