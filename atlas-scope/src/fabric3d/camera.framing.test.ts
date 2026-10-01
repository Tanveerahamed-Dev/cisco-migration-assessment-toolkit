/**
 * camera.framing.test.ts — every framing leaves the stage's overlay bands free (C5 audit).
 *
 * MEASURED before the fix (1600x900, both tiers): the overview put core1 at y = 32 of 900 with its
 * name at y ~ 15, a one-hop trace left core1's "delivered here" chip on its own chassis and core2's
 * name under the Quality chip, and a 400 px downward drag moved core1 9 px because the home view sat
 * 4 degrees off the polar clamp. These tests pin the geometry without a GPU on the REAL layout.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import {
  FRAME_SAFE_INSET_PX,
  createCameraRig,
  frameSphereFromCurrentView,
  safeFrameFor,
} from "./camera";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

function rigAt(width: number, height: number) {
  const canvas = document.createElement("canvas");
  document.body.appendChild(canvas);
  const sphere = layout.framing.boundingSphere;
  const rig = createCameraRig(canvas, {
    framing: layout.framing,
    sphere: { center: sphere.center, radius: sphere.radius },
    box: layout.bounds,
    reducedMotion: true,
    width,
    height,
  });
  // OrbitControls orients the camera toward its target in update(), as the render loop does.
  rig.update(16);
  return rig;
}

/** CSS-pixel position of a world point for a camera at a viewport size. */
function toScreen(cam: PerspectiveCamera, p: Vector3, width: number, height: number): [number, number] {
  cam.updateMatrixWorld();
  const v = p.clone().project(cam);
  return [((v.x + 1) / 2) * width, ((1 - v.y) / 2) * height];
}

describe("the framing keeps the overlay bands free", () => {
  for (const [w, h] of [
    [840, 782],
    [1158, 900],
    [760, 560],
  ] as const) {
    it(`overview at ${w}x${h}: every chassis inside the safe frame`, () => {
      const rig = rigAt(w, h);
      rig.camera.updateMatrixWorld();
      const safe = safeFrameFor(w, h);
      let minY = Infinity;
      let maxY = -Infinity;
      let minX = Infinity;
      let maxX = -Infinity;
      for (const n of layout.nodes) {
        const [x, y] = toScreen(rig.camera, new Vector3(n.x, n.y, n.z), w, h);
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      }
      // The top-tier anchors sit below the top inset (which is where their names and the toolbar
      // go), the bottom tier above the bottom inset, and nothing leaves the sides.
      expect(minY).toBeGreaterThanOrEqual(safe.top * h - 1);
      expect(maxY).toBeLessThanOrEqual(h - safe.bottom * h + 1);
      expect(minX).toBeGreaterThanOrEqual(safe.left * w - 1);
      expect(maxX).toBeLessThanOrEqual(w - safe.right * w + 1);
      // And it still FILLS the band on its binding axis — the insets are not an excuse to shrink.
      const usedV = (maxY - minY) / (h * (1 - safe.top - safe.bottom));
      const usedH = (maxX - minX) / (w * (1 - safe.left - safe.right));
      expect(Math.max(usedV, usedH)).toBeGreaterThan(0.75);
      rig.dispose();
    });
  }

  it("the home view has tilt head-room on both sides of the polar clamp", () => {
    const rig = rigAt(1158, 900);
    const off = rig.camera.position.clone().sub(rig.controls.target);
    const polar = Math.acos(off.y / off.length());
    expect(polar - rig.controls.minPolarAngle).toBeGreaterThanOrEqual((8 * Math.PI) / 180 - 1e-6);
    expect(rig.controls.maxPolarAngle - polar).toBeGreaterThanOrEqual((8 * Math.PI) / 180 - 1e-6);
    rig.dispose();
  });

  it("a focused sphere is centred in the safe band, not in the canvas", () => {
    const rig = rigAt(840, 782);
    const node = layout.nodes[0];
    expect(node).toBeDefined();
    const c = new Vector3(node?.x ?? 0, node?.y ?? 0, node?.z ?? 0);
    const pose = frameSphereFromCurrentView(rig.camera, rig.controls.target, c, 20, 1.4);
    const cam = rig.camera.clone();
    cam.position.set(...pose.position);
    cam.lookAt(...pose.target);
    const [, y] = toScreen(cam, c, 840, 782);
    const bandMid = (FRAME_SAFE_INSET_PX.top + (782 - FRAME_SAFE_INSET_PX.bottom)) / 2;
    expect(Math.abs(y - bandMid)).toBeLessThan(6);
    rig.dispose();
  });
});
