import { describe, expect, it } from "vitest";
import { FRAME_RATE_BAR_FPS, createFrameRateBar, createStepDownJudge } from "./stepdown";

const uniform = (n: number, ms: number): number[] => Array.from({ length: n }, () => ms);
/** The measured orbit shape: mostly 16.7 ms with a share of 33.3 ms frames. */
const bimodal = (n: number, slowShare: number): number[] =>
  Array.from({ length: n }, (_, i) => ((i % 100) < slowShare * 100 ? 33.3 : 16.7));

function run(series: number[]) {
  const judge = createStepDownJudge();
  const bar = createFrameRateBar();
  let stepped = false;
  for (const ms of series) {
    if (judge.push(ms).step) stepped = true;
    bar.push(ms);
  }
  return { stepped, below: bar.below(), fps: bar.reportedFps(), reason: bar.reason() };
}

describe("E4 frame-rate bar: the band the step-down rule tolerates is REPORTED, not passed as health", () => {
  it("is the acceptance bar", () => {
    expect(FRAME_RATE_BAR_FPS).toBe(55);
  });

  it.each([
    ["uniform 20 ms (50 fps)", uniform(300, 20)],
    ["uniform 22 ms (45.5 fps)", uniform(300, 22)],
    ["bimodal 16.7/33.3, 20% slow (~50 fps)", bimodal(300, 0.2)],
    ["bimodal 16.7/33.3, 11% slow (the measured orbit, ~54 fps)", bimodal(300, 0.11)],
  ])("%s: the tier rule holds, and the bar is reported", (_label, series) => {
    const r = run(series);
    expect(r.stepped).toBe(false);
    expect(r.below).toBe(true);
    expect(r.fps).not.toBeNull();
    expect(r.fps as number).toBeLessThan(55);
    expect(r.reason).toMatch(/below the 55 fps bar/);
  });

  it("a machine at the display rate is not reported", () => {
    const r = run(uniform(300, 16.7));
    expect(r.below).toBe(false);
    expect(r.reason).toBe("");
  });

  it.each([70, 100, 200, 500])("a steady %i ms series RAISES the bar (degradation is never silent)", (ms) => {
    const bar = createFrameRateBar();
    for (const x of uniform(600, ms)) bar.push(x);
    expect(bar.below()).toBe(true);
    expect(bar.reportedFps() as number).toBeCloseTo(1000 / ms, 5);
    expect(bar.reason()).toMatch(/below the 55 fps bar/);
  });

  it("the bar is raised within the first window of slow frames, not eventually", () => {
    const bar = createFrameRateBar();
    let at = -1;
    uniform(600, 500).forEach((x, i) => {
      if (bar.push(x) && at < 0) at = i;
    });
    expect(at).toBeGreaterThanOrEqual(0);
    expect(at).toBeLessThan(21);
  });

  it("an unjudgeable window (too short) reports nothing either way", () => {
    const bar = createFrameRateBar();
    for (const ms of uniform(10, 40)) bar.push(ms);
    expect(bar.below()).toBe(false);
  });

  it("clears only once the window is back at the clear rate (no flicker on the bar)", () => {
    const bar = createFrameRateBar();
    for (const ms of uniform(200, 20)) bar.push(ms);
    expect(bar.below()).toBe(true);
    /* 18 ms is 55.6 fps: at the bar, not above the clear rate — still reported. */
    for (const ms of uniform(200, 18)) bar.push(ms);
    expect(bar.below()).toBe(true);
    for (const ms of uniform(200, 16.7)) bar.push(ms);
    expect(bar.below()).toBe(false);
  });

  it("a reset (tier change) lowers the flag: the new tier has not been measured", () => {
    const bar = createFrameRateBar();
    for (const ms of uniform(200, 22)) bar.push(ms);
    expect(bar.below()).toBe(true);
    bar.reset();
    expect(bar.below()).toBe(false);
  });
});
