/**
 * render-c5-repairs.test.ts — the 3-D render defects an independent critic found, pinned.
 *
 * WHAT THESE TESTS PROVE
 *   - A quality-tier change cannot change a chassis's SHAPE: every tier's profile builds the same
 *     geometry (`geometryKey` equal), so the lid louvers can no longer pop to a flat rectangle when
 *     the adaptive step-down fires (design-brief §4.9 #11, "Geometry has no LOD").
 *   - Every state-ring band stands on a curb with real height, so its near arc keeps projected
 *     coverage at the 12-degree grazing view the orbit clamp allows; the dashed and double shapes
 *     are carried by the curb as well.
 *   - The access point's uncollected outline is ONE ring, not the stack of fillet contours edge
 *     detection produced.
 *   - A wheel-zoom after a device focus zooms TOWARD that device: its screen position holds.
 *   - A camera parked at the dolly limit goes idle; OrbitControls' phantom "zoom changed" report
 *     no longer keeps the render loop (and `converged`) busy forever.
 *
 * WHAT THEY DO NOT PROVE
 *   - How any of it looks. The before/after captures are in the repair report (C5): grazing rings,
 *     tier swap diff, AP close-up, torus shading and label placement were each checked on a real
 *     GPU in the running app.
 */
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";
import { Vector3 } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph, geometryKey } from "./scene";
import { createCameraRig, measureDrawnBounds } from "./camera";
import { profileFor } from "./quality";
import { STATE_RING_WALL, buildStateRing, chassisSilhouette } from "./geometry/chassis";

describe("quality tiers change cost, never shape", () => {
  it("builds identical geometry at every tier", () => {
    const keys = (["high", "balanced", "low"] as const).map((t) => geometryKey(profileFor(t)));
    expect(new Set(keys).size).toBe(1);
    for (const t of ["high", "balanced", "low"] as const) {
      expect(profileFor(t).chassisFineDetail).toBe(true);
    }
  });

  it("still steps the post chain down", () => {
    expect(profileFor("low").ssao).toBe(false);
    expect(profileFor("low").bloom).toBe(false);
    expect(profileFor("high").ssao).toBe(true);
  });
});

describe("state rings keep coverage at a grazing view", () => {
  for (const shape of ["solid", "dashed", "double"] as const) {
    it(`the ${shape} ring stands on a curb`, () => {
      const g = buildStateRing(shape);
      g.computeBoundingBox();
      const box = g.boundingBox!;
      expect(box.max.y - box.min.y).toBeGreaterThanOrEqual(STATE_RING_WALL - 1e-6);
      g.dispose();
    });
  }

  it("the double ring's curb is two stripes, not one wall", () => {
    const g = buildStateRing("double");
    const pos = g.getAttribute("position");
    const heights = new Set<number>();
    for (let i = 0; i < pos.count; i += 1) heights.add(Math.round(pos.getY(i) * 1000) / 1000);
    // Flat bands at 0, inner curb top, and the two stripes' four edges.
    expect(heights.size).toBeGreaterThanOrEqual(4);
    g.dispose();
  });
});

describe("the access point's uncollected outline", () => {
  it("is one ring at the widest radius", () => {
    const g = chassisSilhouette("ap");
    const pos = g.getAttribute("position");
    const ys = new Set<number>();
    const radii = new Set<number>();
    for (let i = 0; i < pos.count; i += 1) {
      ys.add(Math.round(pos.getY(i) * 1000));
      radii.add(Math.round(Math.hypot(pos.getX(i), pos.getZ(i)) * 1000));
    }
    expect(ys.size).toBe(1);
    expect(radii.size).toBe(1);
    g.dispose();
  });
});

describe("the camera rig", () => {
  const devices = fabricJson.devices as Device[];
  const links = fabricJson.links as Link[];
  const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
  const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("high") });

  const makeRig = () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const sphere = layout.framing.boundingSphere;
    const rig = createCameraRig(canvas, {
      framing: layout.framing,
      sphere: { center: sphere.center, radius: sphere.radius },
      box: layout.bounds,
      depthBox: measureDrawnBounds(graph.scene),
      reducedMotion: true,
      width: 1158,
      height: 900,
    });
    return { rig, canvas };
  };
  const wheel = (canvas: HTMLCanvasElement, deltaY: number): void => {
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY, clientX: 10, clientY: 10, cancelable: true }));
  };

  it("zooms toward the zoom anchor, holding its screen position", () => {
    const { rig, canvas } = makeRig();
    // A pose whose orbit target is NOT the subject: the subject sits off the view axis.
    const anchor = new Vector3(...layout.framing.target).add(new Vector3(20, 0, 10));
    rig.setZoomAnchor([anchor.x, anchor.y, anchor.z]);
    // Settle the pose first: the rig places the camera but only OrbitControls.update() orients it.
    rig.controls.update();
    rig.camera.updateMatrixWorld();
    const before = anchor.clone().project(rig.camera);
    const d0 = rig.camera.position.distanceTo(rig.controls.target);
    for (let i = 0; i < 4; i += 1) wheel(canvas, -100);
    rig.camera.updateMatrixWorld();
    const after = anchor.clone().project(rig.camera);
    expect(rig.camera.position.distanceTo(rig.controls.target)).toBeLessThan(d0);
    expect(Math.abs(after.x - before.x)).toBeLessThan(1e-3);
    expect(Math.abs(after.y - before.y)).toBeLessThan(1e-3);
    rig.dispose();
    canvas.remove();
  });

  it("without an anchor, keeps OrbitControls' own dolly (the subject drifts)", () => {
    const { rig, canvas } = makeRig();
    const anchor = new Vector3(...layout.framing.target).add(new Vector3(20, 0, 10));
    // Settle the pose first: the rig places the camera but only OrbitControls.update() orients it.
    rig.controls.update();
    rig.camera.updateMatrixWorld();
    const before = anchor.clone().project(rig.camera);
    for (let i = 0; i < 4; i += 1) wheel(canvas, -100);
    rig.camera.updateMatrixWorld();
    const after = anchor.clone().project(rig.camera);
    expect(Math.hypot(after.x - before.x, after.y - before.y)).toBeGreaterThan(1e-2);
    rig.dispose();
    canvas.remove();
  });

  it("goes idle once parked at the dolly-in limit", () => {
    /* The phantom needs the camera parked AT the clamp: the radius OrbitControls recomputes from
       the position then differs from minDistance by a rounding error, and its clamp reports a zoom
       change on every frame. Parking it there directly, at several distances, makes the case
       deterministic rather than dependent on where a run of wheel events happens to stop. */
    const { rig, canvas } = makeRig();
    let t = 1000;
    let phantom = 0;
    for (const k of [0.31, 0.37, 0.43, 0.5, 0.57, 0.63, 0.71, 0.83]) {
      const d = rig.camera.position.distanceTo(rig.controls.target);
      rig.camera.position.sub(rig.controls.target).multiplyScalar(k).add(rig.controls.target);
      rig.controls.minDistance = d * k * (1 + 1e-13);
      rig.update((t += 16));
      for (let i = 0; i < 20; i += 1) if (rig.update((t += 16))) phantom += 1;
    }
    expect(phantom).toBe(0);
    rig.dispose();
    canvas.remove();
  });
});

/* ── capture-motion's motion-spike rule: a neighbourhood that did not change is not a reference ──
 *
 * Acceptance report 2026-09-23 (C5, item 15): the popping FAIL at light/high dolly frame 59 read
 * "Infinityx" — `review/capture-motion.mjs` divided a frame's change rate by the median rate of its
 * moving neighbours, and that median was 0 (sub-pixel damping-tail frames change no pixel). Every
 * frame with any change at all then became an infinite spike, so the item could fail on ordinary
 * motion. The rule is pinned here on synthetic sequences with known answers, both ways: the
 * artefact must not fail, and a real pop must still fail, whether its neighbours moved or not. */
describe("capture-motion: the motion-spike rule has a floor under its reference rate", () => {
  interface Spike { frame: number; ratio: number | null }
  interface MotionModule {
    T: Record<string, number>;
    analyseMotion(
      seq: { id: string; what: string },
      meta: unknown[],
      L: Uint8Array[],
      w: number,
      h: number,
      tier: string,
    ): { motionSpikes: Spike[] };
  }
  const load = async (): Promise<MotionModule> =>
    (await import(/* @vite-ignore */ pathToFileURL(resolve(process.cwd(), "review", "capture-motion.mjs")).href)) as MotionModule;

  const W = 10;
  const H = 10;
  /** Frames whose camera anchor moves `cam[t]` px on frame t and whose luma changes by 10 levels
   *  on `changed[t]` pixels — so frame t's mean change is changed[t] * 10 / 100 levels. */
  const sequence = (cam: number[], changed: number[]): { meta: unknown[]; L: Uint8Array[] } => {
    const meta: unknown[] = [];
    const L: Uint8Array[] = [];
    let x = 100;
    let prev = new Uint8Array(W * H).fill(100);
    for (let t = 0; t < cam.length; t += 1) {
      x += cam[t] ?? 0;
      const cur = new Uint8Array(prev);
      for (let p = 0; p < (changed[t] ?? 0); p += 1) cur[p] = cur[p] === 100 ? 110 : 100;
      L.push(cur);
      prev = cur;
      meta.push({ i: t, ts: t * 16.7, cam: [x, 50], vis: "", hover: null, fade: null, aoSuspended: false, quality: "high", framesTimed: t, w: W, h: H });
    }
    return { meta, L };
  };
  const spikesOf = async (cam: number[], changed: number[]): Promise<Spike[]> => {
    const { analyseMotion } = await load();
    const { meta, L } = sequence(cam, changed);
    return analyseMotion({ id: "known-answer", what: "synthetic" }, meta, L, W, H, "high").motionSpikes;
  };
  const at = (n: number, t: number, v: number, rest: number): number[] => Array.from({ length: n }, (_, k) => (k === t ? v : rest));

  it("states the floor, as a rate a smooth move does not reach", async () => {
    const { T } = await load();
    expect(T.SPIKE_NORM_FLOOR, "the reference rate needs a stated floor").toBeGreaterThan(0);
    expect(Number.isFinite(T.SPIKE_NORM_FLOOR)).toBe(true);
  });

  it("an ordinary camera step among sub-pixel frames that changed nothing is NOT a pop (the Infinityx artefact)", async () => {
    /* Frame 7 moves 1 px and changes 3.0 levels on average: 3 levels per px, inside the smooth range.
       Its eight neighbours crept 0.01 px and changed no pixel, so their median rate is exactly 0. */
    const spikes = await spikesOf(at(14, 7, 1, 0.01), at(14, 7, 30, 0));
    expect(spikes, JSON.stringify(spikes)).toEqual([]);
  });

  it("a real pop among ordinary motion still fails", async () => {
    /* Every frame moves 0.5 px and changes 0.5 levels (1 level/px); frame 7 changes 6 levels. */
    const spikes = await spikesOf(at(14, 7, 0.5, 0.5), at(14, 7, 60, 5));
    expect(spikes.map((s) => s.frame)).toEqual([7]);
  });

  it("a real pop among near-still frames still fails, and its ratio is finite", async () => {
    /* The neighbourhood that made the old rule divide by zero, with a genuine pop in it: frame 7
       moves 0.02 px and changes 5 levels. */
    const spikes = await spikesOf(at(14, 7, 0.02, 0.01), at(14, 7, 50, 0));
    expect(spikes.map((s) => s.frame)).toEqual([7]);
    expect(Number.isFinite(spikes[0]?.ratio ?? Number.NaN), "the reported ratio is against the floored reference").toBe(true);
  });
});

/* ── capture-motion grades a leg only at the tier it declares ────────────────────────────────────
 *
 * Acceptance report 2026-09-23 (C5, harness defect): `analyseMotion` recorded `tiersSeen` and no
 * verdict read it; the tier was checked once, at leg start. The dark "high" reset-fly that failed on
 * a history-blend pop had actually rendered at LOW (the automatic step-down fired mid-leg), and a
 * "high" leg that ran at low reported `legProblems []`. A sequence whose frames were not all rendered
 * at the leg's declared tier is now a FAIL of its own, and a leg problem, so no item is graded on
 * evidence about a tier it does not name. Known answers both ways. */
describe("capture-motion: a sequence is graded only at the tier its leg declares", () => {
  interface TierHeld {
    declared: string;
    tiersSeen: string[];
    frames: number;
    framesOffTier: number;
    firstOffTierFrame: number | null;
    framesUnpinned: number;
    firstUnpinnedFrame: number | null;
  }
  interface TierModule {
    analyseMotion(seq: { id: string; what: string }, meta: unknown[], L: Uint8Array[], w: number, h: number, tier: string): { tiersSeen: string[]; tierHeld: TierHeld };
    declaredTierFails(leg: string, analysed: readonly { sequence: string; tierHeld: TierHeld }[]): string[];
  }
  const load = async (): Promise<TierModule> =>
    (await import(/* @vite-ignore */ pathToFileURL(resolve(process.cwd(), "review", "capture-motion.mjs")).href)) as TierModule;
  const W = 4;
  const H = 4;
  /* `auto` is each frame's `stats().qualityAuto`: false = the leg's tier was PINNED (scene.setQuality),
     so the adaptive step-down could not move it. Omitted, every frame is pinned. */
  const run = async (declared: string, tiers: string[], auto: (boolean | undefined)[] = tiers.map(() => false)) => {
    const m = await load();
    const meta = tiers.map((quality, t) => ({ i: t, ts: t * 16.7, cam: [t * 0.1, 0], vis: "", hover: null, fade: null, aoSuspended: false, quality, qualityAuto: auto[t], framesTimed: t, w: W, h: H }));
    const L = tiers.map(() => new Uint8Array(W * H).fill(90));
    const a = { sequence: "known-answer", ...m.analyseMotion({ id: "known-answer", what: "synthetic" }, meta, L, W, H, declared) };
    return { a, fails: m.declaredTierFails(`dark/${declared}`, [a]) };
  };

  it("a leg declared high whose frames went high -> low FAILS, naming the first off-tier frame", async () => {
    const { a, fails } = await run("high", ["high", "high", "high", "low", "low", "low"]);
    expect(a.tiersSeen).toEqual(["high", "low"]);
    expect(a.tierHeld).toEqual({ declared: "high", tiersSeen: ["high", "low"], frames: 6, framesOffTier: 3, firstOffTierFrame: 3, framesUnpinned: 0, firstUnpinnedFrame: null });
    expect(fails).toHaveLength(1);
    expect(fails[0]).toMatch(/dark\/high\/known-answer: 3 of 6 frames rendered at low, not the declared high \(first at frame 3\)/);
  });

  it("a step-down through balanced is caught too, whatever tier it lands on", async () => {
    const { fails } = await run("high", ["high", "balanced", "balanced", "low"]);
    expect(fails).toHaveLength(1);
    expect(fails[0]).toMatch(/3 of 4 frames rendered at balanced, low/);
  });

  it("a sequence rendered wholly at its declared tier is not a problem, at either tier", async () => {
    expect((await run("high", ["high", "high", "high"])).fails).toEqual([]);
    expect((await run("low", ["low", "low", "low"])).fails).toEqual([]);
  });

  it("a frame with no reported tier is not evidence about the declared one", async () => {
    const { fails } = await run("low", ["low", "", "low"]);
    expect(fails).toHaveLength(1);
    expect(fails[0]).toMatch(/1 of 3 frames rendered at \(none\)/);
  });

  /* C5 at 8e873d2: both HIGH legs rendered at the auto-selected high tier and were stepped down
     mid-orbit. A leg is now PINNED at its declared tier, and the check asserts the pin held on every
     frame: a frame at the right tier but still auto is one the adaptive rule was free to move. */
  it("a frame at the declared tier that was NOT pinned (qualityAuto true) FAILS, naming the first one", async () => {
    const { a, fails } = await run("high", ["high", "high", "high", "high"], [true, true, false, false]);
    expect(a.tierHeld).toMatchObject({ framesOffTier: 0, framesUnpinned: 2, firstUnpinnedFrame: 0 });
    expect(fails).toEqual([expect.stringMatching(/dark\/high\/known-answer: 2 of 4 frames rendered with the tier not pinned \(stats\(\)\.qualityAuto was not false; first at frame 0\)/)]);
  });

  it("a frame with no pin record is not evidence of a pin (fails closed)", async () => {
    const { fails } = await run("low", ["low", "low"], [false, undefined]);
    expect(fails).toEqual([expect.stringMatching(/1 of 2 frames rendered with the tier not pinned/)]);
  });

  it("an off-tier AND unpinned sequence reports both, in one FAIL line", async () => {
    const { fails } = await run("high", ["high", "balanced"], [true, true]);
    expect(fails).toHaveLength(1);
    expect(fails[0]).toMatch(/1 of 2 frames rendered at balanced, not the declared high \(first at frame 1\); 2 of 2 frames rendered with the tier not pinned/);
  });

  it("a sequence whose tier record is missing fails closed rather than passing", async () => {
    const m = await load();
    const fails = m.declaredTierFails("dark/high", [{ sequence: "no-record" } as unknown as { sequence: string; tierHeld: TierHeld }]);
    expect(fails).toEqual([expect.stringMatching(/dark\/high\/no-record: no per-frame tier record/)]);
  });
});
