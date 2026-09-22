/**
 * render-c5-r4.test.ts — the 3-D render repairs of the 2026-09-22 C5/E4 audit, pinned where they
 * can be pinned without a GPU.
 *
 *   E4  a display presenting at 30 Hz (Windows Energy Saver) stepped the tier high -> balanced ->
 *       low for nothing: the frame rate stayed at 30.0 fps. The judge now takes the display's
 *       cadence, measured on idle frames, and does not blame the renderer for it.
 *   E4  after a step-down `qualityReasons` still carried "full quality: ..." next to "stepped down
 *       to low". The probe's sentence is restated for the tier in force.
 *   C5  the low-tier reason said "shadows and SSAO disabled"; it is now derived from the profiles.
 *   C5  the eye could get under the upper tiers after a low-tier focus (polar clamp is about the
 *       target); every pose now looks down on every lid in view.
 *   C5  the dolly floor was 0.55 of the neighbourhood framing; with a device focused it is the
 *       device's own radius.
 *   C5  labels flickered while the camera moved; appearances now wait for a still frame and a
 *       verdict dwells before it reverses.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import {
  createPresentationCadence,
  createStepDownJudge,
  effectiveBars,
  STEP_DOWN_DEFAULTS,
} from "./stepdown";
import {
  chooseQuality,
  FULL_QUALITY_PREFIX,
  probeReasonsAt,
  tierConsequence,
  type GpuCapabilities,
} from "./quality";
import { raiseRigAbout, subjectFloorDistance, visibleLidFloor } from "./camera";
import { LABEL_MIN_DWELL_PASSES, resolveLabels, type LabelResolverState } from "./labelResolve";

describe("E4: a presentation cap is not a slow renderer", () => {
  const feed = (period: number | null, frameMs: number, n = 400): boolean => {
    const judge = createStepDownJudge();
    let stepped = false;
    for (let i = 0; i < n; i += 1) if (judge.push(frameMs, period).step) stepped = true;
    return stepped;
  };

  it("steps down on 33.3 ms frames when the cadence is unknown (the audited failure)", () => {
    expect(feed(null, 33.3)).toBe(true);
  });

  it("does not step down on 33.3 ms frames when the display presents every 33.3 ms", () => {
    expect(feed(33.3, 33.4)).toBe(false);
  });

  it("still steps down at 30 Hz when the renderer misses presentations the display offered", () => {
    expect(feed(33.3, 66.7)).toBe(true);
  });

  it("leaves the bars exactly as configured on a 60 Hz display", () => {
    const b = effectiveBars(STEP_DOWN_DEFAULTS, 16.7);
    expect(b).toEqual({ slowMs: STEP_DOWN_DEFAULTS.slowMs, minFps: STEP_DOWN_DEFAULTS.minFps, displayLimited: false });
    expect(feed(16.7, 33.3)).toBe(true);
  });

  it("measures the cadence only from a tight cluster of idle intervals", () => {
    const c = createPresentationCadence();
    for (let i = 0; i < 11; i += 1) c.noteIdle(33.3);
    expect(c.periodMs()).toBeNull(); // too few samples
    c.noteIdle(33.4);
    expect(c.periodMs()).toBeCloseTo(33.3, 1);
    const noisy = createPresentationCadence();
    for (let i = 0; i < 40; i += 1) noisy.noteIdle(i % 2 === 0 ? 16.7 : 50);
    expect(noisy.periodMs()).toBeNull(); // idle frames stretched by page work are not a display
  });
});

describe("quality reasons follow the tier in force", () => {
  const caps: GpuCapabilities = {
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

  it("derives what low turns off from the profiles, not from a hand-written list", () => {
    expect(tierConsequence("low")).toBe("SSAO, bloom and outline passes disabled");
    const sw = chooseQuality({ ...caps, software: true, rendererName: "Google SwiftShader" });
    expect(sw.reasons.join(" ")).toContain("SSAO, bloom and outline passes disabled");
    expect(sw.reasons.join(" ")).not.toContain("shadows and SSAO");
  });

  it("never says full quality at a tier below high", () => {
    const probe = chooseQuality(caps);
    expect(probe.reasons[0]?.startsWith(FULL_QUALITY_PREFIX)).toBe(true);
    for (const tier of ["balanced", "low"] as const) {
      const r = probeReasonsAt(probe, tier);
      expect(r.join(" ")).not.toContain(FULL_QUALITY_PREFIX);
      expect(r.join(" ")).toContain(`running at ${tier}`);
    }
    expect(probeReasonsAt(probe, "high")).toEqual(probe.reasons);
  });
});

describe("C5: the eye never gets under the fabric", () => {
  const cam = (eye: [number, number, number], target: [number, number, number]): PerspectiveCamera => {
    const c = new PerspectiveCamera(45, 16 / 9, 1, 2000);
    c.position.set(...eye);
    c.lookAt(new Vector3(...target));
    c.updateMatrixWorld();
    return c;
  };

  it("raises a low eye to look down on the lids in view, keeping the pivot on screen", () => {
    // A low-tier target (y 10) seen from 78 degrees, with an upper tier of lids at y 80 in view.
    const target = new Vector3(0, 10, 0);
    const polar = (78 * Math.PI) / 180;
    const d = 200;
    const eye = new Vector3(0, 10 + d * Math.cos(polar), d * Math.sin(polar));
    const lids = Float32Array.from([-40, 80, -60, 0, 80, -60, 40, 80, -60]);
    const c = cam([eye.x, eye.y, eye.z], [target.x, target.y, target.z]);
    const floor = visibleLidFloor(c, lids);
    expect(eye.y).toBeLessThan(floor); // the audited pose breaks the rule
    const pivot = new Vector3(0, 10, 20);
    const before = pivot.clone().project(c);
    expect(raiseRigAbout(eye, target, pivot, floor, (24 * Math.PI) / 180)).toBe(true);
    expect(eye.y).toBeGreaterThanOrEqual(floor - 1e-6);
    const c2 = cam([eye.x, eye.y, eye.z], [target.x, target.y, target.z]);
    const after = pivot.clone().project(c2);
    expect(after.x).toBeCloseTo(before.x, 4);
    expect(after.y).toBeCloseTo(before.y, 4);
  });

  it("never tilts the view steeper than the polar floor", () => {
    const target = new Vector3(0, 0, 0);
    const eye = new Vector3(0, 5, 50);
    raiseRigAbout(eye, target, target, 1e6, (24 * Math.PI) / 180);
    const off = eye.clone().sub(target);
    const polar = Math.acos(off.y / off.length());
    expect(polar).toBeGreaterThanOrEqual((24 * Math.PI) / 180 - 1e-6);
  });

  it("frames a focused chassis, not its neighbourhood, at the dolly floor", () => {
    // A 15 x 3 x 9 chassis: half-diagonal ~8.9. At 45 degrees it fills 55 % of the frame height.
    const r = Math.hypot(7.5, 1.5, 4.5);
    const dist = subjectFloorDistance(r, 45);
    expect(dist).toBeGreaterThan(20);
    expect(dist).toBeLessThan(60);
  });
});

describe("C5: labels do not pop while the camera moves", () => {
  const state = (n: number): LabelResolverState => ({
    wasKept: new Uint8Array(n),
    pending: new Uint8Array(n),
    passesSinceDrop: 99,
    age: new Uint16Array(n).fill(0xffff),
  });
  const run = (s: LabelResolverState, boxes: number[][], moving: boolean): number[] =>
    Array.from(
      resolveLabels(
        {
          boxes: Float32Array.from(boxes.flat()),
          classOf: boxes.map(() => 60),
          distance: boxes.map((_, i) => i),
          hysteresisPx: 5,
          dropEveryPasses: 1,
          settled: false,
          cameraMoving: moving,
        },
        s,
      ).kept,
    );

  it("holds a newly clear name back until the camera is still", () => {
    const s = state(2);
    const overlapping = [
      [0, 0, 100, 15],
      [50, 0, 150, 15],
    ];
    const apart = [
      [0, 0, 100, 15],
      [300, 0, 400, 15],
    ];
    run(s, overlapping, false); // the one-frame temporal hold: pending first
    expect(run(s, overlapping, false)).toEqual([1, 0]);
    for (let i = 0; i < 5; i += 1) expect(run(s, apart, true)).toEqual([1, 0]);
    run(s, apart, false); // still: the temporal hold admits it next pass
    expect(run(s, apart, false)).toEqual([1, 1]);
  });

  it("does not remove a name within the dwell of its appearance", () => {
    const s = state(2);
    const apart = [
      [0, 0, 100, 15],
      [300, 0, 400, 15],
    ];
    const overlapping = [
      [0, 0, 100, 15],
      [50, 0, 150, 15],
    ];
    run(s, apart, false);
    expect(run(s, apart, false)).toEqual([1, 1]);
    for (let i = 0; i < LABEL_MIN_DWELL_PASSES - 2; i += 1) expect(run(s, overlapping, true)[1]).toBe(1);
    let gone = false;
    for (let i = 0; i < 4; i += 1) if (run(s, overlapping, true)[1] === 0) gone = true;
    expect(gone).toBe(true);
  });
});
