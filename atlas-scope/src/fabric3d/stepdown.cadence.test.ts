import { describe, expect, it } from "vitest";
import { FULL_QUALITY_PREFIX, probeReasonsAt } from "./quality";
import {
  STEP_DOWN_DEFAULTS,
  createPresentationCadence,
  createStepDownJudge,
  displayLimitReason,
  effectiveBars,
} from "./stepdown";

/* E4 audit, 2026-09-22 (laptop on battery, Windows Energy Saver ON): Chromium presented at 30 Hz,
   every rAF interval 33.3-33.5 ms. The judge read that as "100% of frames over 24 ms, 30.0 fps" and
   stepped high -> balanced -> low, and the frame rate stayed at exactly 30.0 fps with draw calls cut
   from 78 to 32. These tests pin the repair: a display-limited cadence is not a renderer failure. */

const MEASURED_30HZ = (n: number): number[] => Array.from({ length: n }, (_, i) => (i % 2 === 0 ? 33.3 : 33.5));

function firstStep(series: number[], presentationMs: number | null): number | null {
  const judge = createStepDownJudge();
  for (let i = 0; i < series.length; i += 1) if (judge.push(series[i] ?? 0, presentationMs).step) return i;
  return null;
}

describe("presentation cadence: a display capped at 30 Hz is not a renderer over budget", () => {
  it("the measured 30 Hz series steps down when the cadence is unknown (the audited defect)", () => {
    expect(firstStep(MEASURED_30HZ(240), null)).not.toBeNull();
  });

  it("the same series does NOT step down once the display's 33.3 ms period is known", () => {
    expect(firstStep(MEASURED_30HZ(600), 33.3)).toBeNull();
  });

  it("a renderer missing presentations the 30 Hz display offered still steps down", () => {
    // Every other presentation missed: 66.7 ms frames on a 33.3 ms display is 15 fps, well under 24.
    const series = Array.from({ length: 120 }, () => 66.7);
    expect(firstStep(series, 33.3)).not.toBeNull();
  });

  it("a GPU that cannot keep up on a 60 Hz display is judged exactly as before", () => {
    const series = Array.from({ length: 200 }, () => 28);
    expect(firstStep(series, 16.7)).toBe(firstStep(series, null));
    expect(firstStep(series, 16.7)).not.toBeNull();
    expect(effectiveBars(STEP_DOWN_DEFAULTS, 16.7)).toEqual({
      slowMs: STEP_DOWN_DEFAULTS.slowMs,
      minFps: STEP_DOWN_DEFAULTS.minFps,
      displayLimited: false,
    });
  });

  it("the cadence is read only from a TIGHT cluster of idle intervals", () => {
    const tight = createPresentationCadence();
    for (let i = 0; i < 30; i += 1) tight.noteIdle(i % 3 === 0 ? 33.5 : 33.3);
    expect(tight.periodMs()).toBeCloseTo(33.3, 1);

    // Idle frames stretched by the page's own work are scattered, not clustered: not a display.
    const scattered = createPresentationCadence();
    for (let i = 0; i < 30; i += 1) scattered.noteIdle([16.7, 24, 41, 18, 60, 33][i % 6] ?? 16.7);
    expect(scattered.periodMs()).toBeNull();

    const tooFew = createPresentationCadence();
    for (let i = 0; i < 5; i += 1) tooFew.noteIdle(33.3);
    expect(tooFew.periodMs()).toBeNull();
  });

  it("a display-limited session says so in words", () => {
    /* Worded as what was measured (frames arrive every 33.3 ms even when nothing is drawn), not as
       a cause the probe cannot see: 45 ms of injected per-frame page work reads the same way. */
    expect(displayLimitReason(33.3)).toMatch(/^frame rate capped at 30 Hz by something other than this renderer/);
  });
});

describe("quality reasons below high never claim full quality", () => {
  const probe = {
    tier: "high" as const,
    reasons: [`${FULL_QUALITY_PREFIX}WebGL 2, 16384px textures, 16x anisotropy, Intel`],
    auto: true,
  };

  it("at the probe's own tier the probe's sentence stands", () => {
    expect(probeReasonsAt(probe, "high")[0]?.startsWith(FULL_QUALITY_PREFIX)).toBe(true);
  });

  it.each(["balanced", "low"] as const)("at %s no reason starts with 'full quality'", (tier) => {
    const reasons = probeReasonsAt(probe, tier);
    expect(reasons.some((r) => r.startsWith(FULL_QUALITY_PREFIX))).toBe(false);
    expect(reasons.join(" ")).toContain(`running at ${tier}`);
  });
});
