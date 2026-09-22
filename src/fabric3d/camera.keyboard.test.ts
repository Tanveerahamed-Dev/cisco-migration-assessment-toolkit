/**
 * camera.keyboard.test.ts — keyboard orbit and pan ARE the pointer's orbit and pan (acceptance D1).
 *
 * THE DEFECT (independent acceptance report, 2026-09-22). A 300 px pointer drag on the fabric
 * canvas rotated the view about 90°; none of 25 keys pressed on the focused canvas changed the
 * camera at all. Selection was reachable from the keyboard; viewpoint control was not.
 *
 * THE CONTRACT pinned here: the rig's keyboard verbs (`orbitBy`, `panBy`) take a drag distance in
 * CSS pixels and move the camera EXACTLY as a pointer drag of that distance does — same pose after
 * the drag, same pose after the damping tail — because they drive OrbitControls' own drag handlers,
 * not a second camera model. The drag side of each comparison is a REAL pointer sequence dispatched
 * on the canvas and handled by OrbitControls, not a hand-moved camera. Reduced motion: both land
 * the whole move at once (no inertial tail), and still agree.
 */
import { describe, expect, it } from "vitest";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { createCameraRig, type CameraRig } from "./camera";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

const W = 1158;
const H = 900;

function makeRig(reducedMotion: boolean): { rig: CameraRig; canvas: HTMLCanvasElement } {
  const canvas = document.createElement("canvas");
  // jsdom lays nothing out; OrbitControls divides a drag by the element's clientHeight.
  Object.defineProperty(canvas, "clientHeight", { configurable: true, get: () => H });
  Object.defineProperty(canvas, "clientWidth", { configurable: true, get: () => W });
  canvas.setPointerCapture = () => {};
  canvas.releasePointerCapture = () => {};
  document.body.appendChild(canvas);
  const sphere = layout.framing.boundingSphere;
  const rig = createCameraRig(canvas, {
    framing: layout.framing,
    sphere: { center: sphere.center, radius: sphere.radius },
    box: layout.bounds,
    reducedMotion,
    width: W,
    height: H,
  });
  return { rig, canvas };
}

/** A pointer event OrbitControls accepts: jsdom has no PointerEvent constructor, so a MouseEvent
 *  carrying the pointer fields stands in. */
function pointer(type: string, x: number, y: number, button: number): MouseEvent {
  const e = new MouseEvent(type, { clientX: x, clientY: y, button, bubbles: true, cancelable: true });
  Object.defineProperty(e, "pointerId", { value: 1 });
  Object.defineProperty(e, "pointerType", { value: "mouse" });
  return e;
}

/** A real drag: down, one move of (dx, dy), up — the same sequence a mouse produces. */
function drag(canvas: HTMLCanvasElement, dx: number, dy: number, button: 0 | 2): void {
  const x0 = 400;
  const y0 = 300;
  canvas.dispatchEvent(pointer("pointerdown", x0, y0, button));
  canvas.ownerDocument.dispatchEvent(pointer("pointermove", x0 + dx, y0 + dy, button));
  canvas.ownerDocument.dispatchEvent(pointer("pointerup", x0 + dx, y0 + dy, button));
}

const pose = (rig: CameraRig): number[] => [...rig.camera.position.toArray(), ...rig.controls.target.toArray()];

function settle(rig: CameraRig): void {
  for (let i = 0; i < 240; i += 1) rig.update(1000 + i * 16);
}

function expectSamePose(a: number[], b: number[]): void {
  expect(a.length).toBe(b.length);
  for (let i = 0; i < a.length; i += 1) expect(a[i]!, `component ${i}`).toBeCloseTo(b[i]!, 9);
}

describe("keyboard orbit and pan drive the pointer's own camera path (D1)", () => {
  for (const reduced of [false, true]) {
    const mode = reduced ? "reduced motion" : "full motion";

    it(`orbit: orbitBy(dx, dy) lands exactly where a primary-button drag of (dx, dy) does — ${mode}`, () => {
      const a = makeRig(reduced);
      const b = makeRig(reduced);
      const start = pose(a.rig);
      expectSamePose(pose(b.rig), start);

      drag(a.canvas, 50, -30, 0);
      b.rig.orbitBy(50, -30);
      // Immediately after the gesture, before any frame: the same partial (or, reduced, whole) move.
      expectSamePose(pose(b.rig), pose(a.rig));
      settle(a.rig);
      settle(b.rig);
      expectSamePose(pose(b.rig), pose(a.rig));
      // Control: the drag really moved the camera, so "equal" is not two untouched rigs.
      const moved = pose(a.rig).some((v, i) => Math.abs(v - start[i]!) > 1e-3);
      expect(moved, "the pointer drag did not move the camera; the comparison proves nothing").toBe(true);
    });

    it(`pan: panBy(dx, dy) lands exactly where a secondary-button drag of (dx, dy) does — ${mode}`, () => {
      const a = makeRig(reduced);
      const b = makeRig(reduced);
      const start = pose(a.rig);
      drag(a.canvas, -40, 25, 2);
      b.rig.panBy(-40, 25);
      expectSamePose(pose(b.rig), pose(a.rig));
      settle(a.rig);
      settle(b.rig);
      expectSamePose(pose(b.rig), pose(a.rig));
      // A pan moves the TARGET; an orbit does not. That is what makes this a pan.
      const t0 = start.slice(3);
      const t1 = pose(a.rig).slice(3);
      expect(t1.some((v, i) => Math.abs(v - t0[i]!) > 1e-3), "the pan drag did not move the target").toBe(true);
    });
  }

  it("reduced motion: a key orbit lands whole — no inertial tail after the press", () => {
    const { rig } = makeRig(true);
    rig.orbitBy(60, 0);
    const after = pose(rig);
    settle(rig);
    expectSamePose(pose(rig), after);
  });

  it("full motion: the key orbit carries the same eased tail a drag does (damping is the pointer's)", () => {
    const { rig } = makeRig(false);
    rig.orbitBy(60, 0);
    const after = pose(rig);
    settle(rig);
    expect(pose(rig).some((v, i) => Math.abs(v - after[i]!) > 1e-6)).toBe(true);
  });
});
