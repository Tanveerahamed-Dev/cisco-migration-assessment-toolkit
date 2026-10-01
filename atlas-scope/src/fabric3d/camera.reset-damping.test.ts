/**
 * camera.reset-damping.test.ts — a programmatic camera move lands EXACTLY where it was sent, and
 * nothing a user gesture left behind moves it afterwards (acceptance A5, repair wave 6).
 *
 * THE DEFECT (independent refuter at 78bdba5, SwiftShader, 3-9 fps). A 240 px orbit drag, a 300 ms
 * wait, then Reset view: core1 settled at (410.7, 91.7) against a home pose of (474.4, 82.2) —
 * ~64 px off — and stayed there. The control (a 20 s wait before Reset) returned to home. The Home
 * key drifted too. The error GREW as the frame rate fell.
 *
 * THE CAUSE. OrbitControls keeps a gesture's inertia as pending deltas (rotation, pan) that its
 * `update()` decays by `dampingFactor` PER FRAME, not per millisecond. `moveTo()` tweened position
 * and target but left those deltas in place, so the rig's per-frame `controls.update()` kept adding
 * them on top of every tween frame and after the tween landed. Fewer frames in the 300 ms before
 * Reset = more of the tail still pending = a larger error; that is the frame-rate dependence.
 *
 * THE CLASS pinned here is "a programmatic move that a still-coasting (or newly started) user
 * gesture can corrupt": every programmatic move goes through `moveTo` (home, Reset view, device
 * focus, trace re-framing, the immediate/reduced-motion jump), so each is driven here after a REAL
 * gesture dispatched on the canvas and handled by OrbitControls — a primary drag (orbit), a
 * secondary drag (pan), a wheel dolly, and the keyboard verbs that replay the pointer's handlers —
 * at 60, 9 and 3 fps. The oracle for "home" is an untouched rig's construction pose, which is
 * `homePose()` computed without any gesture history; the oracle for a device framing is the pose
 * object passed to `moveTo`.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import {
  CAMERA_TWEEN_MS,
  createCameraRig,
  frameSphereFromCurrentView,
  pendingInertiaOf,
  type CameraRig,
  type CameraTarget,
} from "./camera";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

/* The refuter's stage: 1920x1080 window, a 1158x900 fabric canvas. */
const W = 1158;
const H = 900;
const TOL = 1e-6;
/** Frames the pose must stay put for after the move lands (the brief's 120). */
const HOLD_FRAMES = 120;

function makeRig(reducedMotion = false): { rig: CameraRig; canvas: HTMLCanvasElement } {
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

/** jsdom has no PointerEvent constructor; a MouseEvent carrying the pointer fields stands in. */
function pointer(type: string, x: number, y: number, button: number): MouseEvent {
  const e = new MouseEvent(type, { clientX: x, clientY: y, button, bubbles: true, cancelable: true });
  Object.defineProperty(e, "pointerId", { value: 1 });
  Object.defineProperty(e, "pointerType", { value: "mouse" });
  return e;
}

/** A frame clock: every `step` ms, as the render loop's rAF would call `rig.update(now)`. */
class Clock {
  now = 1000;
  constructor(readonly step: number) {}
  frame(rig: CameraRig): void {
    this.now += this.step;
    rig.update(this.now);
  }
  /** Frames for `ms` of wall time at this frame rate (at least one). */
  run(rig: CameraRig, ms: number): void {
    const n = Math.max(1, Math.round(ms / this.step));
    for (let i = 0; i < n; i += 1) this.frame(rig);
  }
}

/** The refuter's drag: 20 moves of (+12, +4) px, a frame between each (a real mouse at the frame rate). */
function dragOnCanvas(rig: CameraRig, canvas: HTMLCanvasElement, clock: Clock, button: 0 | 2): void {
  let x = 400;
  let y = 300;
  canvas.dispatchEvent(pointer("pointerdown", x, y, button));
  for (let i = 0; i < 20; i += 1) {
    x += 12;
    y += 4;
    canvas.ownerDocument.dispatchEvent(pointer("pointermove", x, y, button));
    clock.frame(rig);
  }
  canvas.ownerDocument.dispatchEvent(pointer("pointerup", x, y, button));
}

type Gesture = "orbit drag" | "pan drag" | "wheel dolly" | "key orbit" | "key pan";
const GESTURES: readonly Gesture[] = ["orbit drag", "pan drag", "wheel dolly", "key orbit", "key pan"];

function gesture(kind: Gesture, rig: CameraRig, canvas: HTMLCanvasElement, clock: Clock): void {
  switch (kind) {
    case "orbit drag":
      dragOnCanvas(rig, canvas, clock, 0);
      return;
    case "pan drag":
      dragOnCanvas(rig, canvas, clock, 2);
      return;
    case "wheel dolly":
      // A wheel dolly is applied inside the handler; the ORBIT still coasting from the drag before
      // it is what a wheel leaves pending. Both are real events on the canvas.
      dragOnCanvas(rig, canvas, clock, 0);
      for (let i = 0; i < 4; i += 1) {
        canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -120, clientX: W / 2, clientY: H / 2, cancelable: true }));
        clock.frame(rig);
      }
      return;
    case "key orbit":
      for (let i = 0; i < 6; i += 1) {
        rig.orbitBy(40, 0);
        clock.frame(rig);
      }
      return;
    case "key pan":
      for (let i = 0; i < 6; i += 1) {
        rig.panBy(40, 0);
        clock.frame(rig);
      }
      return;
  }
}

const poseOf = (rig: CameraRig): number[] => [...rig.camera.position.toArray(), ...rig.controls.target.toArray()];
const flat = (t: CameraTarget): number[] => [...t.position, ...t.target];

/** Largest component-wise error between the rig's pose and `want`. */
const err = (rig: CameraRig, want: number[]): number =>
  poseOf(rig).reduce((m, v, i) => Math.max(m, Math.abs(v - want[i]!)), 0);

/** The home pose, from a rig that has never seen a gesture: `homePose()` with no history. */
function homeOracle(): number[] {
  return poseOf(makeRig().rig);
}

/**
 * Advance until the tween has landed, then HOLD_FRAMES more; returns the WORST error seen from the
 * landing frame on, so a pose that lands right and then drifts fails as surely as one that lands wrong.
 */
function landAndHold(rig: CameraRig, clock: Clock, want: number[]): { landed: number; worst: number; tweenFrames: number } {
  let tweenFrames = 0;
  while (rig.isTweening() && tweenFrames < 10_000) {
    clock.frame(rig);
    tweenFrames += 1;
  }
  const landed = err(rig, want);
  let worst = landed;
  for (let i = 0; i < HOLD_FRAMES; i += 1) {
    clock.frame(rig);
    worst = Math.max(worst, err(rig, want));
  }
  return { landed, worst, tweenFrames };
}

const RATES: ReadonlyArray<readonly [string, number]> = [
  ["60 fps", 1000 / 60],
  ["9 fps", 1000 / 9],
  ["3 fps", 1000 / 3],
];

describe("a programmatic move cancels the pending damping tail (A5)", () => {
  for (const [rate, step] of RATES) {
    for (const g of GESTURES) {
      it(`home() 300 ms after a ${g} lands on homePose and stays there — ${rate}`, () => {
        const want = homeOracle();
        const { rig, canvas } = makeRig();
        const clock = new Clock(step);
        gesture(g, rig, canvas, clock);
        // Control: the gesture really moved the camera, so "back home" is not an untouched rig.
        expect(err(rig, want), `the ${g} did not move the camera; the test proves nothing`).toBeGreaterThan(1);
        clock.run(rig, 300);
        rig.home();
        expect(rig.isTweening(), "home() did not start the eased move").toBe(true);
        const r = landAndHold(rig, clock, want);
        expect(r.tweenFrames * step, "the tween ended early").toBeGreaterThanOrEqual(CAMERA_TWEEN_MS - step);
        expect(r.landed, "the tween did not land on homePose").toBeLessThan(TOL);
        expect(r.worst, `the pose drifted within ${HOLD_FRAMES} frames of landing`).toBeLessThan(TOL);
      });
    }
  }

  for (const [rate, step] of RATES) {
    it(`moveTo(a device framing) 300 ms after an orbit drag lands on that framing — ${rate}`, () => {
      const { rig, canvas } = makeRig();
      const clock = new Clock(step);
      const node = layout.nodes.find((n) => n.host === "core1") ?? layout.nodes[0]!;
      const framing = frameSphereFromCurrentView(
        rig.camera,
        rig.controls.target,
        new Vector3(node.x, node.y, node.z),
        40,
        1.35,
      );
      dragOnCanvas(rig, canvas, clock, 0);
      clock.run(rig, 300);
      rig.moveTo(framing);
      const r = landAndHold(rig, clock, flat(framing));
      expect(r.landed, "the focus fly-to did not land on its framing").toBeLessThan(TOL);
      expect(r.worst, "the focused pose drifted after landing").toBeLessThan(TOL);
    });
  }

  for (const g of GESTURES) {
    it(`home({ immediate: true }) after a ${g} jumps to homePose and nothing moves it afterwards`, () => {
      const want = homeOracle();
      const { rig, canvas } = makeRig();
      const clock = new Clock(1000 / 9);
      gesture(g, rig, canvas, clock);
      clock.run(rig, 300);
      rig.home({ immediate: true });
      expect(rig.isTweening()).toBe(false);
      expect(err(rig, want), "the immediate jump did not land on homePose").toBeLessThan(TOL);
      const r = landAndHold(rig, clock, want);
      expect(r.worst, "the pose drifted after the immediate jump").toBeLessThan(TOL);
    });
  }

  it("reduced motion switched on mid-coast: Reset jumps to homePose and stays", () => {
    const want = homeOracle();
    const { rig, canvas } = makeRig(false);
    const clock = new Clock(1000 / 9);
    dragOnCanvas(rig, canvas, clock, 0);
    rig.setReducedMotion(true);
    rig.home();
    expect(rig.isTweening(), "reduced motion must jump, not ease").toBe(false);
    expect(err(rig, want)).toBeLessThan(TOL);
    const r = landAndHold(rig, clock, want);
    expect(r.worst).toBeLessThan(TOL);
  });

  it("reduced motion switched on mid-TWEEN after a gesture: the move lands whole on homePose", () => {
    const want = homeOracle();
    const { rig, canvas } = makeRig(false);
    const clock = new Clock(1000 / 9);
    dragOnCanvas(rig, canvas, clock, 0);
    rig.home();
    clock.frame(rig);
    // A key orbit in flight, then the switch lands the move before another frame runs: the landing
    // must not carry the orbit's delta (with damping now off it would be applied WHOLE).
    expect(rig.isTweening()).toBe(true);
    rig.orbitBy(80, 0);
    rig.setReducedMotion(true);
    expect(rig.isTweening()).toBe(false);
    const r = landAndHold(rig, clock, want);
    expect(r.landed).toBeLessThan(TOL);
    expect(r.worst).toBeLessThan(TOL);
  });

  for (const [rate, step] of RATES) {
    it(`a gesture made DURING the tween cannot knock it off its landing — ${rate}`, () => {
      const want = homeOracle();
      const { rig, canvas } = makeRig();
      const clock = new Clock(step);
      dragOnCanvas(rig, canvas, clock, 0);
      clock.run(rig, 300);
      rig.home();
      clock.frame(rig);
      // A key orbit and a whole pan drag while the move is in flight (no frame passes during the
      // drag, so all of it happens inside the tween at every frame rate).
      expect(rig.isTweening()).toBe(true);
      rig.orbitBy(80, 0);
      canvas.dispatchEvent(pointer("pointerdown", 500, 400, 2));
      canvas.ownerDocument.dispatchEvent(pointer("pointermove", 560, 430, 2));
      canvas.ownerDocument.dispatchEvent(pointer("pointerup", 560, 430, 2));
      expect(rig.isTweening()).toBe(true);
      const r = landAndHold(rig, clock, want);
      expect(r.landed, "the in-flight gesture moved the landing").toBeLessThan(TOL);
      expect(r.worst, "the in-flight gesture's tail moved the pose after landing").toBeLessThan(TOL);
    });
  }

  it("the pending-inertia accessor fails loud when three stops exposing a field it discards", () => {
    const canvas = document.createElement("canvas");
    // The real controls pass: this is the shape the discard above was proven against.
    expect(() => pendingInertiaOf(new OrbitControls(new PerspectiveCamera(), canvas))).not.toThrow();
    for (const field of ["_sphericalDelta", "_panOffset", "_scale", "_performCursorZoom"]) {
      const c = new OrbitControls(new PerspectiveCamera(), canvas);
      delete (c as unknown as Record<string, unknown>)[field];
      expect(() => pendingInertiaOf(c), `missing ${field} was accepted`).toThrow(/pending-inertia/);
    }
  });

  it("after the move lands, the next gesture still orbits with its damping tail (the fix is not a lock)", () => {
    const { rig, canvas } = makeRig();
    const clock = new Clock(1000 / 60);
    dragOnCanvas(rig, canvas, clock, 0);
    clock.run(rig, 300);
    rig.home();
    landAndHold(rig, clock, homeOracle());
    const landed = poseOf(rig);
    rig.orbitBy(60, 0);
    const afterPress = poseOf(rig);
    expect(afterPress.some((v, i) => Math.abs(v - landed[i]!) > 1e-3), "the key orbit after landing did nothing").toBe(true);
    clock.run(rig, 500);
    expect(poseOf(rig).some((v, i) => Math.abs(v - afterPress[i]!) > 1e-6), "the orbit lost its damping tail").toBe(true);
  });
});
