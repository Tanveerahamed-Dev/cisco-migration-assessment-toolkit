/**
 * camera.occlusion.test.ts — Reset view frames the fabric in the stage the reader can SEE (A5).
 *
 * MEASURED before the fix: with the Fabric list open, Reset view framed against the whole canvas,
 * so core1's chassis sat at the top edge under the panel and the off-view pointer ("F106 core1 off
 * view") fired on the very view Reset had just produced. With the list closed it framed correctly.
 * The list is 34ch wide at the top-left of the stage and spans nearly its full height; these tests
 * report that band through `setStageOcclusion` and check the REAL layout on the REAL rig.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { createCameraRig, safeFrameFor, setStageOcclusion } from "./camera";
import { isGoldenSample } from "../test-support/golden-sample";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

function rigAt(canvas: HTMLCanvasElement, width: number, height: number) {
  const sphere = layout.framing.boundingSphere;
  const rig = createCameraRig(canvas, {
    framing: layout.framing,
    sphere: { center: sphere.center, radius: sphere.radius },
    box: layout.bounds,
    reducedMotion: true,
    width,
    height,
  });
  rig.update(16);
  return rig;
}

function extent(cam: PerspectiveCamera, width: number, height: number) {
  cam.updateMatrixWorld();
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const n of layout.nodes) {
    const v = new Vector3(n.x, n.y, n.z).project(cam);
    const x = ((v.x + 1) / 2) * width;
    const y = ((1 - v.y) / 2) * height;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  return { minX, maxX, minY, maxY };
}

describe("an open overlay panel is subtracted from the framing", () => {
  for (const [w, h, listPx] of [
    [1158, 900, 320],
    [840, 782, 320],
  ] as const) {
    it(`Reset at ${w}x${h} with a ${listPx}px list on the left: every chassis right of the list`, () => {
      const canvas = document.createElement("canvas");
      document.body.appendChild(canvas);
      const rig = rigAt(canvas, w, h);

      setStageOcclusion(canvas, { top: 0, bottom: 0, left: listPx, right: 0 });
      rig.home({ immediate: true });
      rig.update(16);
      const e = extent(rig.camera, w, h);
      const safe = safeFrameFor(w, h, { top: 0, bottom: 0, left: listPx, right: 0 });

      expect(e.minX, "no chassis anchor under the open list").toBeGreaterThanOrEqual(listPx);
      expect(e.minX).toBeGreaterThanOrEqual(safe.left * w - 1);
      expect(e.maxX).toBeLessThanOrEqual(w - safe.right * w + 1);
      expect(e.minY).toBeGreaterThanOrEqual(safe.top * h - 1);
      expect(e.maxY).toBeLessThanOrEqual(h - safe.bottom * h + 1);

      // Closing the list gives the band back: the next Reset uses the whole stage again.
      setStageOcclusion(canvas, null);
      rig.home({ immediate: true });
      rig.update(16);
      const open = extent(rig.camera, w, h);
      /* RE-EXPRESSED 2026-09-29 (P3C-V2-3): "the band is given back" used to be read as "some chassis now sits
         under where the list was" (open.minX < listPx), which is a fact about how WIDE one fabric frames — a
         narrow fabric (the engine's 7-device golden) framed on the whole stage still clears 320 px. What closing
         the list gives back on ANY fabric is the band itself: the framing moves into it (its leftmost chassis is
         left of where the occluded framing put it) and spreads wider. The sample's reading is pinned below. */
      expect(open.minX, "the framing moves into the band the list gave back").toBeLessThan(e.minX - 1);
      expect(open.maxX - open.minX, "and uses the width it gained").toBeGreaterThanOrEqual(e.maxX - e.minX - 1);
      if (isGoldenSample()) expect(open.minX, "on the reference sample a chassis sits where the list was").toBeLessThan(listPx);
      rig.dispose();
      canvas.remove();
    });
  }

  it("reporting occlusion does not move the camera by itself", () => {
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const rig = rigAt(canvas, 1158, 900);
    const before = rig.camera.position.clone();
    setStageOcclusion(canvas, { top: 0, bottom: 0, left: 320, right: 0 });
    rig.update(16);
    expect(rig.camera.position.distanceTo(before)).toBeLessThan(1e-6);
    rig.dispose();
    canvas.remove();
  });

  it("never lets a panel take the whole stage", () => {
    const s = safeFrameFor(800, 600, { top: 0, bottom: 0, left: 790, right: 0 });
    expect(s.left + s.right).toBeLessThanOrEqual(0.65 + 1e-9);
  });
});
