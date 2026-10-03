/**
 * trace-framing.test.ts — a trace's own framing keeps every hop host, its ending and its name on the
 * stage (acceptance A5).
 *
 * THE DEFECT (independent refuter, A5, 2026-10-02, r7-frame-sweep.mjs at 1920x1080): of 74 swept
 * flows, 20 auto-framed with a hop host off the canvas — every flow sourced in 10.0.20.0/24, which
 * crosses core2 -> core1. The trace framed only the bounding sphere of the drawn CABLE (radius
 * max(6, ...)), and that cable is short: the camera zoomed onto it and both chassis, both names and
 * the terminal glyph projected outside the canvas (core1 at y = -408 on a 962 px stage).
 *
 * WHAT THESE TESTS PROVE, on the REAL layout, the REAL cables and REAL traces from the engine:
 *   - for every swept flow and every supported stage size, the pose the trace frames puts every hop
 *     host's chassis (all eight corners), the terminal glyph where it will actually be drawn for that
 *     pose, and the head-room its label needs above it, inside the framing safe frame;
 *   - a device-focus pose that would leave part of that outside is not taken as-is.
 * WHAT THEY DO NOT PROVE: the pixels. The browser sweep (r7-frame-sweep.mjs re-run against a build)
 * is the measurement; this keeps the geometry from being quietly reverted.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Flow, Link, Trace } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { computeLayout } from "./layout";
import { createCameraRig, safeFrameFor, type CameraTarget } from "./camera";
import { createFlowOverlay, placeTerminalGlyph, STOP_GLYPH_RADIUS, UNDECIDED_GLYPH_RADIUS } from "./flow";
import { readTokens } from "./materials";
import { profileFor } from "./quality";
import { LABEL_LIFT, LABEL_LIFT_BLOCKED } from "./labelResolve";
import { buildFabricGraph, traceAnchorIn, tracePolylineIn } from "./scene";
import { traceEndOf } from "./traceEnd";
import { traceFramingPose } from "./traceFraming";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("high") });
const source = {
  polylineBetween: (a: string, b: string) => tracePolylineIn(graph, a, b),
  anchorOf: (h: string) => traceAnchorIn(graph, h),
};

/**
 * The fabric canvas's CSS size at each supported viewport, MEASURED on the production build (the
 * stage is what is left of the window beside the panels; r9-hosts-glyph-labels.mjs): 1920x1080 ->
 * 1160x962, 1440x900 -> 760x790, 1280x800 -> 600x690, 768x1024 -> 768x471, 390x844 -> 390x388 (the
 * fabric shown on request). Plus two odd aspects so the sweep is not tuned to five numbers.
 */
const STAGES: readonly (readonly [number, number])[] = [
  [1160, 962],
  [760, 790],
  [600, 690],
  [768, 471],
  [390, 388],
  [1600, 500],
  [360, 900],
];

/** A label's height, px (a hop label with its chip measures 15-17 px on the build). */
const LABEL_H = 17;

/** The refuter's sweep (6 sources x 7 destinations x 2 services) plus the sample's suggested flows. */
function sweptFlows(): Flow[] {
  const srcs = ["10.0.40.50", "10.0.41.50", "10.0.20.50", "10.0.10.50", "10.0.30.10", "10.0.20.10"];
  const dsts = ["10.0.10.50", "10.0.30.10", "198.51.100.7", "10.0.20.10", "10.0.41.50", "10.0.40.50", "8.8.8.8"];
  const out: Flow[] = [];
  for (const s of srcs) for (const d of dsts) for (const p of [22, 443]) {
    if (s !== d) out.push({ srcIp: s, dstIp: d, protocol: "tcp", dstPort: p, srcPort: null });
  }
  for (const s of suggestedFlows()) out.push(s.flow);
  return out;
}

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
  rig.update(16);
  return rig;
}

function cameraAt(pose: CameraTarget, like: PerspectiveCamera): PerspectiveCamera {
  const cam = like.clone();
  cam.up.set(0, 1, 0);
  cam.position.set(...pose.position);
  cam.lookAt(...pose.target);
  cam.updateMatrixWorld();
  return cam;
}

/**
 * Everything a trace's ending must keep on the stage for `cam`, as screen points with what each is:
 * every hop host's chassis corners, the terminal glyph's extremes, and the top of the label hung
 * above the glyph (or above the chassis when there is no glyph).
 */
function requiredScreenPoints(trace: Trace, cam: PerspectiveCamera, w: number, h: number): { what: string; x: number; y: number }[] {
  const out: { what: string; x: number; y: number }[] = [];
  const toScreen = (p: Vector3): [number, number] => {
    const v = p.clone().project(cam);
    return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * h];
  };
  const end = traceEndOf(trace);
  for (const host of new Set(trace.hops.map((x) => x.host))) {
    const s = graph.slots.get(host);
    if (s === undefined) continue;
    let top = Infinity;
    for (let k = 0; k < 8; k += 1) {
      const [x, y] = toScreen(
        new Vector3(
          s.centre[0] + (k & 1 ? s.half[0] : -s.half[0]),
          s.centre[1] + (k & 2 ? s.half[1] : -s.half[1]),
          s.centre[2] + (k & 4 ? s.half[2] : -s.half[2]),
        ),
      );
      out.push({ what: `${host} chassis`, x, y });
      top = Math.min(top, y);
    }
    // FabricLabels: the ending's host is lifted LABEL_LIFT_BLOCKED label heights unless undecided.
    const lift = end !== null && end.host === host && end.kind !== "undetermined" ? LABEL_LIFT_BLOCKED : LABEL_LIFT;
    if (end !== null && end.host === host && end.kind !== "delivered") {
      const r = end.kind === "blocked" ? STOP_GLYPH_RADIUS : UNDECIDED_GLYPH_RADIUS;
      const anchor = traceAnchorIn(graph, host);
      expect(anchor).not.toBeNull();
      const c = placeTerminalGlyph(anchor!, cam.quaternion, r, new Vector3());
      const up = new Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
      const right = new Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
      for (const [d, sgn] of [[up, 1], [up, -1], [right, 1], [right, -1]] as const) {
        const [x, y] = toScreen(c.clone().addScaledVector(d, sgn * r));
        out.push({ what: `${host} glyph`, x, y });
        top = Math.min(top, y);
      }
    }
    const [cx] = toScreen(new Vector3(s.centre[0], s.centre[1], s.centre[2]));
    out.push({ what: `${host} label head-room`, x: cx, y: top - lift * LABEL_H });
  }
  return out;
}

/** The violations of the safe frame for one trace at one stage size, as readable strings. */
function offFrame(trace: Trace, pose: CameraTarget, like: PerspectiveCamera, w: number, h: number): string[] {
  const cam = cameraAt(pose, like);
  const safe = safeFrameFor(w, h);
  const x0 = safe.left * w - 1;
  const x1 = w - safe.right * w + 1;
  const y0 = safe.top * h - 1;
  const y1 = h - safe.bottom * h + 1;
  const bad: string[] = [];
  for (const p of requiredScreenPoints(trace, cam, w, h)) {
    /* The top of every hop host's label — its chip included — clears the safe frame's top inset,
       which is where the stage toolbar floats: MEASURED at 390x844 the toolbar wraps to three rows
       and a chip pushed into it was displaced down across its own ring. */
    if (p.x < x0 || p.x > x1 || p.y < y0 || p.y > y1) {
      bad.push(`${p.what} (${p.x.toFixed(0)}, ${p.y.toFixed(0)})`);
    }
  }
  return [...new Set(bad.map((b) => b.replace(/ \(.*/, "")))];
}

function frameOf(trace: Trace, rig: ReturnType<typeof rigAt>, focusPose: (host: string) => CameraTarget | null = () => null): CameraTarget | null {
  const overlay = createFlowOverlay(readTokens("dark"));
  try {
    overlay.setTrace(trace, 0, source);
    return traceFramingPose({
      camera: rig.camera,
      currentTarget: rig.controls.target,
      trace,
      pathPoints: overlay.pathPoints(),
      boxOf: (host) => graph.slots.get(host) ?? null,
      focusPose,
    });
  } finally {
    overlay.dispose();
  }
}

describe("a trace frames every hop host, its ending and its name (acceptance A5)", () => {
  const traces = sweptFlows()
    .map((f) => ({ f, t: traceFlow(f) }))
    .filter(({ t }) => t.hops.length > 0);

  it("the refuter's case is in the sweep: traces that cross core2 -> core1", () => {
    const viaCore2 = traces.filter(({ t }) => t.hops[0]?.host === "core2" && t.hops.some((h) => h.host === "core1"));
    expect(viaCore2.length).toBeGreaterThanOrEqual(20);
    expect(traces.filter(({ t }) => new Set(t.hops.map((h) => h.host)).size > 1).length).toBeGreaterThan(40);
  });

  for (const [w, h] of STAGES) {
    it(`at a ${w}x${h} stage, no swept flow leaves a hop host, glyph or label off the safe frame`, () => {
      const rig = rigAt(w, h);
      try {
        const failures: string[] = [];
        for (const { f, t } of traces) {
          const pose = frameOf(t, rig);
          expect(pose).not.toBeNull();
          const bad = offFrame(t, pose!, rig.camera, w, h);
          if (bad.length > 0) failures.push(`${f.srcIp}>${f.dstIp} tcp/${f.dstPort}: ${bad.join(", ")}`);
        }
        expect(failures).toEqual([]);
      } finally {
        rig.dispose();
      }
    });
  }

  it("a device-focus pose that would crop the ending is not taken as-is", () => {
    const rig = rigAt(1160, 962);
    try {
      const t = traceFlow({ srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null });
      expect(new Set(t.hops.map((x) => x.host)).size).toBe(1);
      const host = t.hops[0]!.host;
      const s = graph.slots.get(host)!;
      // A pose looking at the host from so close that its chassis overflows the stage.
      const crop: CameraTarget = {
        position: [s.centre[0], s.centre[1] + 6, s.centre[2] + 8],
        target: [s.centre[0], s.centre[1], s.centre[2]],
      };
      expect(offFrame(t, crop, rig.camera, 1160, 962).length).toBeGreaterThan(0);
      const pose = frameOf(t, rig, () => crop);
      expect(pose).not.toBeNull();
      expect(offFrame(t, pose!, rig.camera, 1160, 962)).toEqual([]);
    } finally {
      rig.dispose();
    }
  });
});
