/**
 * capturePin.test.ts — the capture harness's pin holds the two clock-derived things the chrome draws,
 * and nothing else gets it (acceptance F6, F2's capture delegate).
 *
 * The defect (re-grade refuter F6): on a busy host `node review/capture.mjs twice 5`
 * exited 3 because 08-path-indeterminate was stepped down to `balanced` on some loads and drew
 * "below frame-rate bar" on others, both derived from rAF timing. The repair is a declared opt-in
 * (./capturePin) the harness sets before mount. jsdom has no WebGL, so the scene itself cannot be run
 * here: what is pinned is the decision the scene renders with (through the REAL capability probe and
 * the same `tierIsAdaptive` predicate the scene's step-down sites gate on) and the bar it reports
 * through — each beside its control, so a pin that changed nothing could not pass. That the scene
 * wires them is proved in a browser: the harness refuses a frame whose `stats().capturePin` is absent
 * or not in force.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAPTURE_PIN_GLOBAL, capturePinRequested, freezeFrameRateBar, pinForCapture } from "./capturePin";
import { chooseQuality, pinQuality, tierIsAdaptive, type GpuCapabilities } from "./quality";
import { createFrameRateBar } from "./stepdown";

/** A capable GPU's capabilities, as `probeCapabilities` reports them (the probe reads no clock). */
const CAPABLE: GpuCapabilities = {
  webgl2: true,
  maxTextureSize: 16384,
  maxSamples: 8,
  maxAnisotropy: 16,
  rendererName: "ANGLE (Intel)",
  software: false,
  floatLinearFiltering: true,
  hardwareConcurrency: 16,
  deviceMemoryGb: 16,
};

afterEach(() => {
  vi.unstubAllEnvs();
  delete window.__atlasCapturePin;
});

describe("capturePinRequested — only a capture that asked gets the pin", () => {
  it("is off for an ordinary visitor of the production build", () => {
    vi.stubEnv("DEV", false);
    expect(capturePinRequested()).toBe(false);
  });

  it("is off on the development server too, unlike the scene handle (the adaptive rule is exercised there)", () => {
    vi.stubEnv("DEV", true);
    expect(capturePinRequested()).toBe(false);
  });

  it("is on when the pre-mount global is exactly true, and only then", () => {
    expect(CAPTURE_PIN_GLOBAL).toBe("__atlasCapturePin");
    window.__atlasCapturePin = true;
    expect(capturePinRequested()).toBe(true);
    (window as unknown as Record<string, unknown>)[CAPTURE_PIN_GLOBAL] = "1";
    expect(capturePinRequested()).toBe(false);
  });
});

describe("pinForCapture — the tier the scene renders a capture at", () => {
  it("control: the probe's own high is ADAPTIVE, so a slow host may step it down", () => {
    const probe = chooseQuality(CAPABLE);
    expect(probe.tier).toBe("high");
    expect(tierIsAdaptive(probe)).toBe(true);
  });

  it("holds the probe's high as a pin the step-down and step-up cannot move, and says so", () => {
    const probe = chooseQuality(CAPABLE);
    const { decision, pin } = pinForCapture(probe);
    expect(decision.tier).toBe("high");
    expect(decision.auto).toBe(false);
    /* The predicate the scene's step-down judge and held step-down both gate on, and `auto` is what
       the hidden-page step-up gates on: a pinned capture is outside all three. */
    expect(tierIsAdaptive(decision)).toBe(false);
    /* Already a pin: re-pinning the same tier is a no-op that keeps the capture's reason. */
    expect(pinQuality(decision, "high").decision).toBe(decision);
    expect(pin).toEqual({ tier: "high", applied: true, rateBarFrozen: true, reason: decision.reasons[0] });
    expect(decision.reasons[0]).toMatch(/pinned at high for a capture/);
    /* The probe's evidence about the GPU is kept, not replaced. */
    expect(decision.reasons.slice(1)).toEqual(probe.reasons);
  });

  it.each([
    ["a software rasteriser", { software: true, rendererName: "Google SwiftShader" }, "low"],
    ["four logical cores", { hardwareConcurrency: 4 }, "balanced"],
    ["a 2048 px texture limit", { maxTextureSize: 2048 }, "low"],
  ] as const)("does not raise %s to high: the pin is recorded as NOT applied and the probe's decision stands", (_l, over, tier) => {
    const probe = chooseQuality({ ...CAPABLE, ...over });
    expect(probe.tier).toBe(tier);
    const { decision, pin } = pinForCapture(probe);
    expect(decision).toBe(probe);
    expect(pin.applied).toBe(false);
    expect(pin.rateBarFrozen).toBe(false);
    expect(pin.reason).toContain(`chose ${tier}`);
  });
});

describe("freezeFrameRateBar — the status line's 'below frame-rate bar' cannot follow a busy host", () => {
  /* 25 fps for 6 s of drawn frames: well under the 55 fps bar, long enough to judge. */
  const slow = Array.from({ length: 150 }, () => 40);

  it("control: the real bar raises its flag on that series", () => {
    const bar = createFrameRateBar();
    for (const ms of slow) bar.push(ms);
    expect(bar.below()).toBe(true);
    expect(bar.reason()).toMatch(/below the 55 fps bar/);
  });

  it("frozen, the same series raises nothing, and the real bar underneath was never fed", () => {
    const inner = createFrameRateBar();
    const bar = freezeFrameRateBar(inner);
    for (const ms of slow) expect(bar.push(ms)).toBe(false);
    expect(bar.below()).toBe(false);
    expect(bar.reportedFps()).toBeNull();
    expect(bar.reason()).toBe("");
    expect(inner.below()).toBe(false);
    bar.reset();
    expect(inner.below()).toBe(false);
  });
});
