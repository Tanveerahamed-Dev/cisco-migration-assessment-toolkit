import { describe, expect, it } from "vitest";
import {
  createForeignWorkLedger,
  createGestureGate,
  createStepDownJudge,
  createStepUpPolicy,
  frameIsFabricEvidence,
} from "./stepdown";

function feed(series: number[], judge = createStepDownJudge()) {
  let tripped: { at: number; reason: string } | null = null;
  series.forEach((ms, i) => {
    const v = judge.push(ms);
    if (v.step && !tripped) tripped = { at: i, reason: v.reason };
  });
  return tripped as { at: number; reason: string } | null;
}

/** The measured failure: p50 16.7 ms, p95 50 ms, sustained median ~39 fps. */
function bimodal(frames: number, slowEvery: number, slowMs: number): number[] {
  return Array.from({ length: frames }, (_, i) => (i % slowEvery === 0 ? slowMs : 16.7));
}

/** The +1/-1 counter this replaced, kept here only to prove what it could not see. */
function legacyCounterTrips(series: number[]): boolean {
  let c = 0;
  for (const ms of series) {
    c = ms > 24 ? c + 1 : Math.max(0, c - 1);
    if (c >= 45) return true;
  }
  return false;
}

describe("adaptive step-down judge", () => {
  it("steps down on the measured bimodal series the +1/-1 counter never tripped on", () => {
    const series = bimodal(600, 3, 50); // one frame in three at 50 ms ≈ 36 fps sustained
    expect(legacyCounterTrips(series)).toBe(false);
    const t = feed(series);
    expect(t).not.toBeNull();
    expect(t!.reason).toMatch(/rendered frames were over 24 ms/);
    // Within a few seconds of motion, not "eventually".
    expect(t!.at).toBeLessThan(120);
  });

  it("steps down on a uniformly slow series (every frame 28 ms)", () => {
    expect(feed(Array(300).fill(28))).not.toBeNull();
  });

  it("does not step down on a healthy 60 fps series", () => {
    expect(feed(Array(2000).fill(16.7))).toBeNull();
  });

  it("does not step down on one catastrophic hitch in otherwise healthy motion", () => {
    const series = Array(400).fill(16.7);
    series[50] = 1200;
    expect(feed(series)).toBeNull();
  });

  it("does not step down on occasional slow frames well under the fraction", () => {
    expect(feed(bimodal(2000, 20, 40))).toBeNull(); // 5% over
  });

  it("never judges a window that is too short to be sustained", () => {
    // 10 frames, capped at 100 ms each, span 1 s of the 2 s window: not yet sustained evidence.
    expect(feed(Array(10).fill(200))).toBeNull();
    expect(feed(Array(25).fill(16.7))).toBeNull();
  });

  /* The window used to need BOTH 2 s of capped time AND 30 frames. Below ~14.3 fps a 2 s window
     cannot hold 30 frames, so the judge went silent exactly when the machine was worst (measured
     under CDP 4x CPU throttling: 4-12 fps with the tier still "high"). */
  it.each([70, 100, 200, 500])("steps down on a steady %i ms series (the slow machine is not silent)", (ms) => {
    const j = createStepDownJudge();
    let t: { at: number; reason: string } | null = null;
    for (let i = 0; i < 600 && !t; i += 1) {
      const v = j.push(ms);
      if (v.step) t = { at: i, reason: v.reason };
    }
    expect(t).not.toBeNull();
    // Within the first window: 2 s of capped time is at most 29 such frames.
    expect(t!.at).toBeLessThan(30);
    expect(j.windowFps()).not.toBeNull();
    // The sentence carries the TRUE rate, not the capped test statistic.
    expect(t!.reason).toContain(`${(1000 / ms).toFixed(1)} fps`);
  });

  it("reset forgets the window", () => {
    const j = createStepDownJudge();
    for (let i = 0; i < 100; i += 1) j.push(40);
    j.reset();
    expect(j.size()).toBe(0);
    expect(j.push(40).step).toBe(false);
  });
});

describe("adaptive step-up recovery (the step-down is not a one-way ratchet)", () => {
  it("retries one tier up after the scene has been idle, never above the session's own ceiling", () => {
    const p = createStepUpPolicy({ idleMs: 6000, maxRetries: 1 });
    p.setCeiling("high");
    expect(p.poll("low", 5999)).toBeNull(); // not idle long enough: never mid-gesture
    expect(p.poll("low", 6000)).toBe("balanced");
    expect(p.poll("balanced", 9000)).toBe("high");
    expect(p.poll("high", 60000)).toBeNull(); // at the ceiling
  });

  it("a tier that fails its retry becomes the ceiling: bounded popping, not oscillation", () => {
    const p = createStepUpPolicy({ idleMs: 1000, maxRetries: 1 });
    p.setCeiling("high");
    expect(p.poll("balanced", 2000)).toBe("high");
    p.noteStepDown("high"); // the retry did not hold
    expect(p.strikes("high")).toBe(1);
    expect(p.poll("balanced", 1e9)).toBeNull();
  });

  it("an ordinary step-down (not a retry) costs no strike", () => {
    const p = createStepUpPolicy({ idleMs: 1000, maxRetries: 1 });
    p.setCeiling("high");
    p.noteStepDown("high");
    expect(p.strikes("high")).toBe(0);
    expect(p.poll("balanced", 1000)).toBe("high");
  });

  it("does nothing without a ceiling (a caller-pinned tier is never moved)", () => {
    expect(createStepUpPolicy().poll("low", 1e9)).toBeNull();
  });
});

describe("attribution: a slow frame the PAGE produced is not blamed on the fabric", () => {
  it("excuses a frame whose interval is mostly a foreign long task", () => {
    const ledger = createForeignWorkLedger();
    ledger.noteFrame(1000);
    ledger.noteFrame(1150);
    // A 120 ms React commit in a timer task between the two frames.
    ledger.noteLongTask(1010, 120);
    expect(ledger.foreignMs(1000, 1150)).toBe(120);
    expect(frameIsFabricEvidence(ledger, 1000, 1150)).toBe(false);
  });

  it("never excuses the rendering task that ran a fabric frame, however slow", () => {
    const ledger = createForeignWorkLedger();
    ledger.noteFrame(1000);
    ledger.noteFrame(1400);
    // The frame at 1000 itself took 380 ms: that IS the fabric's evidence.
    ledger.noteLongTask(1001, 380);
    expect(ledger.foreignMs(1000, 1400)).toBe(0);
    expect(frameIsFabricEvidence(ledger, 1000, 1400)).toBe(true);
  });

  it("counts a GPU-bound stretch (no main-thread task at all) as evidence", () => {
    const ledger = createForeignWorkLedger();
    ledger.noteFrame(1000);
    ledger.noteFrame(1050);
    expect(frameIsFabricEvidence(ledger, 1000, 1050)).toBe(true);
  });

  it("keeps a machine that really is slow stepping down when page work is interleaved", () => {
    /* Every frame 30 ms of the fabric's own time, plus a foreign task every tenth interval. The
       excused frames must not rescue a tier the remaining frames prove the machine cannot hold. */
    const ledger = createForeignWorkLedger();
    const judge = createStepDownJudge();
    let t = 0;
    let stepped = false;
    for (let i = 0; i < 400 && !stepped; i++) {
      const from = t;
      ledger.noteFrame(from);
      if (i % 10 === 0) ledger.noteLongTask(from + 31, 90);
      t += i % 10 === 0 ? 125 : 30;
      if (frameIsFabricEvidence(ledger, from, t)) stepped = judge.push(t - from).step;
    }
    expect(stepped).toBe(true);
  });

  it("forgets what it has pruned", () => {
    const ledger = createForeignWorkLedger();
    ledger.noteLongTask(10, 100);
    ledger.prune(5000);
    expect(ledger.foreignMs(0, 200)).toBe(0);
  });
});

describe("gesture gate: a tier change never lands on an interaction's path", () => {
  it("holds a verdict inside the quiet window after a key, a wheel notch or a click", () => {
    const g = createGestureGate({ quietMs: 1000, maxHeldMs: 4000, maxHoldMs: 6000 });
    g.noteInput(10_000);
    expect(g.mayLand(10_016, 10_016, false)).toBe(false);
    expect(g.mayLand(10_999, 10_016, false)).toBe(false);
    expect(g.mayLand(11_000, 10_016, false)).toBe(true);
    g.notePointer(true, 12_000);
    g.notePointer(false, 12_080);
    expect(g.mayLand(12_500, 12_500, false)).toBe(false);
    expect(g.mayLand(13_080, 12_500, false)).toBe(true);
  });

  it("holds while a pointer is down and while the camera tweens", () => {
    const g = createGestureGate({ quietMs: 1000, maxHeldMs: 4000, maxHoldMs: 6000 });
    g.notePointer(true, 0);
    expect(g.mayLand(2_000, 2_000, false)).toBe(false);
    expect(g.mayLand(3_999, 2_000, false)).toBe(false);
    // A pointer held past maxHeldMs (a lost pointerup, a sustained orbit) stops holding the gate.
    expect(g.mayLand(4_000, 2_000, false)).toBe(true);
    const h = createGestureGate({ quietMs: 1000, maxHeldMs: 4000, maxHoldMs: 6000 });
    expect(h.mayLand(50_000, 50_000, true)).toBe(false);
    expect(h.mayLand(50_000, 50_000, false)).toBe(true);
  });

  it("is bounded: a held verdict older than maxHoldMs lands whatever the page is doing", () => {
    const g = createGestureGate({ quietMs: 1000, maxHeldMs: 4000, maxHoldMs: 6000 });
    let t = 0;
    for (; t < 10_000; t += 100) {
      g.noteInput(t);
      if (g.mayLand(t, 0, true)) break;
    }
    expect(t).toBe(6_000);
  });

  it("with no input ever recorded, a verdict lands on the first frame (no silent delay)", () => {
    const g = createGestureGate();
    expect(g.mayLand(5, 5, false)).toBe(true);
  });
});
