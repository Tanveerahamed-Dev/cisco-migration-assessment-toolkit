/**
 * camera.test.ts — the depth range encloses what is drawn, at every pose the user can reach.
 *
 * WHY THIS FILE EXISTS (C5 audit, 2026-09-21). At the dolly-in limit core2 rendered as a sliver of
 * lid with no bezel and a bundle of bridge cables began in mid-air; at the dolly-out limit the whole
 * fabric vanished. Two causes, both pinned here:
 *
 *   1. A wheel dolly never refitted near/far. OrbitControls applies the dolly inside its own wheel
 *      handler and calls `update()` there, so the rig's per-frame `controls.update()` found nothing
 *      left to do, returned false, and the refit it gated never ran. The test drives a REAL wheel
 *      event through the controls rather than moving the camera by hand, because moving it by hand
 *      is exactly the path that already worked.
 *   2. The range was fitted to the node sphere, not to what is drawn. The floor is ~1.7x the
 *      fabric's span; at the overview pose it reached past the far plane.
 *
 * The geometry is the REAL scene graph (`buildFabricGraph` over the compiled snapshot), and the
 * oracle for "what is drawn" is three's own `Box3.setFromObject` per object and per instance — not
 * `measureDrawnBounds`, which is the code under test.
 */
import { describe, expect, it } from "vitest";
import { Box3, InstancedMesh, Matrix4, Vector3, type Object3D } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph } from "./scene";
import { createCameraRig, measureDrawnBounds, type CameraRig } from "./camera";
import { profileFor } from "./quality";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("high") });

/**
 * Every drawn object, boxed. Plain objects by three's own `Box3.setFromObject`; an instanced mesh
 * one box PER INSTANCE, because three's object-level box for an instanced mesh is the union of all
 * its instances — a box whose corners (the right-most chassis x the top-most tier) no chassis
 * occupies, which would report clipping of geometry that does not exist.
 */
function drawnBoxes(root: Object3D): Array<{ name: string; box: Box3 }> {
  root.updateMatrixWorld(true);
  const out: Array<{ name: string; box: Box3 }> = [];
  root.traverse((o) => {
    const name = o.name || o.type;
    if (o instanceof InstancedMesh) {
      o.geometry.computeBoundingBox();
      const local = o.geometry.boundingBox;
      if (local === null) return;
      const m = new Matrix4();
      for (let i = 0; i < o.count; i += 1) {
        o.getMatrixAt(i, m);
        out.push({ name, box: local.clone().applyMatrix4(m).applyMatrix4(o.matrixWorld) });
      }
      return;
    }
    if ((o as { geometry?: unknown }).geometry === undefined) return;
    // Without descending: setFromObject includes children, and the children are visited anyway.
    const box = new Box3();
    const kids = o.children.slice();
    o.children.length = 0;
    box.setFromObject(o);
    o.children.push(...kids);
    if (!box.isEmpty()) out.push({ name, box });
  });
  return out;
}

const BOXES = drawnBoxes(graph.scene);

function makeRig(): { rig: CameraRig; canvas: HTMLCanvasElement } {
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
}

/** Objects the current near/far would clip, judged by view depth along the rig's view axis. */
function clipped(rig: CameraRig): string[] {
  const cam = rig.camera;
  const fwd = new Vector3().copy(rig.controls.target).sub(cam.position).normalize();
  const c = new Vector3();
  const bad: string[] = [];
  for (const { name, box } of BOXES) {
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = 0; i < 8; i += 1) {
      c.set(
        i & 1 ? box.max.x : box.min.x,
        i & 2 ? box.max.y : box.min.y,
        i & 4 ? box.max.z : box.min.z,
      );
      const z = c.sub(cam.position).dot(fwd);
      lo = Math.min(lo, z);
      hi = Math.max(hi, z);
    }
    if (hi <= 0) continue; // wholly behind the camera: not drawable from here at all
    if (hi > cam.far) bad.push(`${name}: depth ${hi.toFixed(1)} > far ${cam.far}`);
    // Near is floored at 1. An object straddling the camera plane (the floor, from above it) can
    // only be enclosed from that floor; anything wholly in front must lie past near.
    if (lo > 0 && lo < cam.near) bad.push(`${name}: depth ${lo.toFixed(1)} < near ${cam.near}`);
    if (lo <= 0 && cam.near !== 1) bad.push(`${name}: straddles the camera with near ${cam.near}`);
  }
  return [...new Set(bad)];
}

function wheel(canvas: HTMLCanvasElement, deltaY: number, times: number, rig: CameraRig): void {
  for (let i = 0; i < times; i += 1) {
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY, clientX: 10, clientY: 10, cancelable: true }));
    rig.update(1000 + i * 16);
  }
}

describe("camera depth range — encloses the drawn scene", () => {
  it("the oracle sees the floor, the object the node sphere never covered", () => {
    expect(BOXES.some((b) => b.name === "floor")).toBe(true);
  });

  it("encloses everything at the overview pose", () => {
    const { rig } = makeRig();
    expect(clipped(rig)).toEqual([]);
  });

  it("a wheel dolly-in refits near/far (OrbitControls applies it inside its own handler)", () => {
    const { rig, canvas } = makeRig();
    const before = rig.camera.position.distanceTo(rig.controls.target);
    const nearBefore = rig.camera.near;
    wheel(canvas, -240, 12, rig);
    const after = rig.camera.position.distanceTo(rig.controls.target);
    // Control: the wheel really moved the camera. Without this, "near/far unchanged" would pass
    // against a controls object that ignored the event.
    expect(after).toBeLessThan(before * 0.7);
    expect(rig.camera.near).not.toBe(nearBefore);
    expect(clipped(rig)).toEqual([]);
  });

  it("a wheel dolly-out refits far, so the fabric does not vanish past it", () => {
    const { rig, canvas } = makeRig();
    const before = rig.camera.position.distanceTo(rig.controls.target);
    wheel(canvas, 400, 20, rig);
    expect(rig.camera.position.distanceTo(rig.controls.target)).toBeGreaterThan(before * 1.8);
    expect(clipped(rig)).toEqual([]);
  });

  it("encloses everything across the reachable orbit x dolly band", () => {
    const { rig } = makeRig();
    const target = rig.controls.target.clone();
    const home = rig.camera.position.distanceTo(target);
    const failures: string[] = [];
    for (const dist of [home * 0.55, home, home * 2.4]) {
      for (const polarDeg of [24, 50, 78]) {
        for (let az = 0; az < 360; az += 45) {
          const p = (polarDeg * Math.PI) / 180;
          const a = (az * Math.PI) / 180;
          const pos = new Vector3(
            Math.sin(p) * Math.sin(a),
            Math.cos(p),
            Math.sin(p) * Math.cos(a),
          )
            .multiplyScalar(dist)
            .add(target);
          rig.moveTo({ position: pos.toArray() as [number, number, number], target: target.toArray() as [number, number, number] }, { immediate: true });
          for (const f of clipped(rig)) failures.push(`d=${dist.toFixed(0)} polar=${polarDeg} az=${az}: ${f}`);
        }
      }
    }
    expect(failures).toEqual([]);
  });
});
