/**
 * A caller-pinned tier is never stepped down — including a pin of the tier ALREADY in force.
 *
 * WHY (acceptance C5, 2026-09-23). `review/capture-motion.mjs` judges each render-quality leg at
 * the tier it declares. Its HIGH legs took the tier the probe auto-selected and asked for it with
 * `setQuality("high")` — which was a no-op, because `setQuality` returned early when the requested
 * tier was the one in force, leaving the decision `auto`. On a contended Intel iGPU both HIGH legs
 * were then stepped down to balanced part-way through their orbits by the (correct) adaptive rule,
 * and four C5 items graded UNPROVEN on evidence about a tier the leg did not name. A caller that
 * asks for the tier it already has is asking to KEEP it: that is a pin, and a pin is outside the
 * adaptive rule.
 *
 * The loop below is the scene's own step-down path, restated from its pure parts: every rendered
 * frame is judged by `createStepDownJudge` only while `tierIsAdaptive(decision)`, and a step lands
 * as an auto decision one tier lower (scene.ts `landHeldStepDown`). The tripwire at the bottom
 * keeps scene.ts on those same parts, so this is not a test of a parallel copy.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { QualityTier } from "./contract";
import { pinQuality, tierIsAdaptive, type QualityDecision } from "./quality";
import { createStepDownJudge } from "./stepdown";

const AUTO_HIGH: QualityDecision = { tier: "high", reasons: ["full quality: probe"], auto: true };

/** A sustained below-bar series: uniform 40 ms frames (25 fps), well past the judge's window. */
const SLOW = Array.from({ length: 300 }, () => 40);

/** The scene's step-down path over `series`, from `start`. Returns every tier it rendered at. */
function run(start: QualityDecision, series: number[]): { decision: QualityDecision; tiers: QualityTier[] } {
  let decision = start;
  const judge = createStepDownJudge();
  const tiers: QualityTier[] = [];
  for (const ms of series) {
    tiers.push(decision.tier);
    if (!tierIsAdaptive(decision)) continue;
    if (judge.push(ms).step) {
      judge.reset();
      decision = { tier: decision.tier === "high" ? "balanced" : "low", reasons: ["stepped down"], auto: true };
    }
  }
  return { decision, tiers };
}

describe("a pinned render-quality tier is not stepped down", () => {
  it("CONTROL: the series is below the bar — an auto-selected high tier IS stepped down by it", () => {
    const r = run(AUTO_HIGH, SLOW);
    expect(r.decision.tier).not.toBe("high");
    expect(r.decision.auto).toBe(true);
  });

  it("pinning the tier already in force makes it a pin: not auto, no rebuild, reason says who set it", () => {
    const pin = pinQuality(AUTO_HIGH, "high");
    expect(pin.decision.tier).toBe("high");
    expect(pin.decision.auto).toBe(false);
    expect(pin.rebuild).toBe(false);
    expect(pin.decision.reasons.join(" ")).toMatch(/set by the caller/);
  });

  it("re-pinning the tier already pinned is a no-op (same decision, its reason intact)", () => {
    const pinned: QualityDecision = { tier: "balanced", reasons: ['quality tier "balanced" requested by the caller'], auto: false };
    const pin = pinQuality(pinned, "balanced");
    expect(pin.decision).toBe(pinned);
    expect(pin.rebuild).toBe(false);
  });

  it("a pinned high tier holds high on every frame of a sustained below-bar series", () => {
    const r = run(pinQuality(AUTO_HIGH, "high").decision, SLOW);
    expect(new Set(r.tiers)).toEqual(new Set(["high"]));
    expect(r.decision).toMatchObject({ tier: "high", auto: false });
  });

  it.each(["high", "balanced"] as const)("a caller changing the tier to %s pins it too (and rebuilds)", (q) => {
    const from: QualityDecision = { tier: q === "high" ? "low" : "high", reasons: ["x"], auto: true };
    const pin = pinQuality(from, q);
    expect(pin).toMatchObject({ rebuild: true, decision: { tier: q, auto: false } });
    expect(new Set(run(pin.decision, SLOW).tiers)).toEqual(new Set([q]));
  });
});

describe("scene.ts uses these parts (tripwire: source text)", () => {
  const source = readFileSync(resolve(process.cwd(), "src/fabric3d/scene.ts"), "utf8");

  it("setQuality goes through pinQuality, and pins in place without a rebuild when the tier is unchanged", () => {
    const body = source.slice(source.indexOf("setQuality(q: QualityTier): void {"), source.indexOf("\n    resize(w: number, h: number): void {"));
    expect(body).toContain("pinQuality(decision, q)");
    expect(body).toMatch(/if \(pin\.rebuild\) \{\s*applyQuality\(pin\.decision\);/);
    expect(body).not.toMatch(/if \(q === decision\.tier\) return;/);
  });

  it("the step-down judge and the held step-down both gate on tierIsAdaptive(decision)", () => {
    expect(source).toContain("if (tierIsAdaptive(decision) && heldStepDown === null) {");
    const land = source.slice(source.indexOf("function landHeldStepDown(now: number): boolean {"));
    expect(land.slice(0, 200)).toContain("if (!tierIsAdaptive(decision)) {");
    expect(source).not.toMatch(/decision\.auto && decision\.tier !== "low"/);
  });
});
