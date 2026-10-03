/**
 * traceFraming.ts — where the camera goes when a trace arrives.
 *
 * THE CONTRACT: the trace's own framing shows the whole statement it makes — every hop host's
 * chassis, the terminal glyph where it will be drawn for that pose, and (through the safe frame's
 * top inset) the room for the names and the verdict chip hung above them. It keeps the direction the
 * reader is already looking from; only the distance and the centre change.
 *
 * MEASURED BEFORE (independent refuter, A5, 2026-10-02, r7-frame-sweep.mjs): every trace that
 * crossed core2 -> core1 — 20 of 74 swept flows — framed the bounding sphere of the drawn CABLE
 * (radius max(6, ...)) at 1.35. That cable is short, so the camera zoomed onto it: core1 projected
 * at y = -408 and core2 past the right edge of a 1160 x 962 stage, labelsShown fell to 1 (0 at
 * 1280x800), and what remained was an unlabelled stub of cable with no name and no verdict glyph.
 * A sphere is the right subject for one device and the wrong one for a path: the path's extent is the
 * union of the chassis it crosses, which the cable between two adjacent chassis does not contain.
 *
 * Pure: the scene hands in its camera, its hop boxes and its focus pose, so the framing is proven on
 * the real layout without a GPU (trace-framing.test.ts).
 */
import { Matrix4, Quaternion, Vector3, type PerspectiveCamera } from "three";
import type { Trace } from "../core/types";
import { currentViewBasis, framePointsFromCurrentView, poseKeepsInSafeFrame, type CameraTarget } from "./camera";
import { placeTerminalGlyph, STOP_GLYPH_RADIUS, UNDECIDED_GLYPH_RADIUS } from "./flow";
import { LABEL_LIFT, LABEL_LIFT_BLOCKED } from "./labelResolve";
import { traceEndOf } from "./traceEnd";

/**
 * Padding on the projected span of everything a trace must show, on top of the safe frame (which
 * already holds the room for the labels and the toolbar). Small, because the subject is the chassis
 * corners and the glyph themselves, not a loose sphere around them.
 */
const TRACE_MARGIN = 1.12;
/**
 * The smallest radius, in multiples of the largest hop chassis' own bounding radius, the framed
 * subject is given about its centre — so a trace of two adjacent chassis reads as a place in the
 * fabric rather than a close-up of two boxes (the same floor the hop-device framing always used).
 */
const CONTEXT_RADII = 3;

/**
 * A DOM label's height, CSS px, for the head-room the trace leaves above its subject. Measured on the
 * production build: a hop host's label with its verdict chip is 15-17 px tall; 20 leaves slack for
 * a larger root font size.
 */
const TRACE_LABEL_PX = 20;

/**
 * Pixels the trace's subject keeps clear above it, beyond the safe frame: the verdict chip's label
 * hung above the ending (LABEL_LIFT label heights, or LABEL_LIFT_BLOCKED for a blocked or delivered
 * ending). The safe frame's top inset was sized for the desktop toolbar plus an ordinary name; on a
 * phone the toolbar wraps to three rows, and MEASURED (390x844, core1 -> dist1) the chip, with no
 * room above the ring, was displaced down across it.
 */
export function traceLabelRoomPx(trace: Trace): number {
  const end = traceEndOf(trace);
  const lift = end !== null && end.kind !== "undetermined" ? LABEL_LIFT_BLOCKED : LABEL_LIFT;
  return lift * TRACE_LABEL_PX;
}

/** A hop host's chassis body: centre and half-extents, world units. */
export interface HostBox {
  centre: readonly [number, number, number];
  half: readonly [number, number, number];
}

export interface TraceFramingInput {
  camera: PerspectiveCamera;
  currentTarget: Vector3;
  trace: Trace;
  /** The drawn path's polyline, xyz triples (flow.ts `pathPoints`); empty when none was stitched. */
  pathPoints: Float32Array;
  boxOf(host: string): HostBox | null;
  /** The pose a device focus would take for `host` (scene.ts `focusFramingFor`). */
  focusPose(host: string): CameraTarget | null;
}

/**
 * The world points a trace's framing must keep inside the safe frame, for a camera looking along
 * `dir` with screen axes `right` / `up`: all eight corners of every hop host's chassis, and the four
 * screen-extreme points of the terminal glyph placed exactly as flow.ts places it for that camera.
 */
export function traceSubjectPoints(
  trace: Trace,
  boxOf: (host: string) => HostBox | null,
  dir: Vector3,
  right: Vector3,
  up: Vector3,
): Vector3[] {
  const out: Vector3[] = [];
  for (const host of new Set(trace.hops.map((h) => h.host))) {
    const b = boxOf(host);
    if (b === null) continue;
    for (let k = 0; k < 8; k += 1) {
      out.push(
        new Vector3(
          b.centre[0] + (k & 1 ? b.half[0] : -b.half[0]),
          b.centre[1] + (k & 2 ? b.half[1] : -b.half[1]),
          b.centre[2] + (k & 4 ? b.half[2] : -b.half[2]),
        ),
      );
    }
  }
  const end = traceEndOf(trace);
  const endBox = end === null || end.kind === "delivered" ? null : boxOf(end.host);
  if (end !== null && endBox !== null) {
    const r = end.kind === "blocked" ? STOP_GLYPH_RADIUS : UNDECIDED_GLYPH_RADIUS;
    // The camera orientation the fitted pose will have: right, up, and looking along -dir.
    const q = new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(right, up, dir));
    const c = placeTerminalGlyph(
      { x: endBox.centre[0], y: endBox.centre[1], z: endBox.centre[2], top: endBox.centre[1] + endBox.half[1], half: endBox.half },
      q,
      r,
      new Vector3(),
    );
    out.push(
      c.clone().addScaledVector(up, r),
      c.clone().addScaledVector(up, -r),
      c.clone().addScaledVector(right, r),
      c.clone().addScaledVector(right, -r),
    );
  }
  return out;
}

/** The pose a trace frames, or null when nothing of it is placed on the fabric. */
export function traceFramingPose(input: TraceFramingInput): CameraTarget | null {
  const { camera, currentTarget, trace, boxOf } = input;
  const dir = new Vector3();
  const right = new Vector3();
  const up = new Vector3();
  currentViewBasis(camera, currentTarget, dir, right, up);
  const subject = traceSubjectPoints(trace, boxOf, dir, right, up);
  if (subject.length === 0) return null;

  /* One distinct hop device frames exactly as focusing it would (the device and the neighbourhood
     it sits in) — as long as that pose keeps the chassis and its glyph inside the safe frame. It is
     checked, not assumed: the focus framing is fitted to a neighbourhood and biased toward it. */
  const hosts = new Set(trace.hops.map((h) => h.host));
  const only = hosts.size === 1 ? [...hosts][0] : undefined;
  const room = traceLabelRoomPx(trace);
  if (only !== undefined) {
    const pose = input.focusPose(only);
    if (pose !== null && poseKeepsInSafeFrame(camera, pose, subject, room)) return pose;
  }

  const points = [...subject];
  const p = input.pathPoints;
  for (let i = 0; i + 2 < p.length; i += 3) points.push(new Vector3(p[i] ?? 0, p[i + 1] ?? 0, p[i + 2] ?? 0));
  /* The context floor: a disc across the line of sight about the subject's centre, so two adjacent
     chassis are framed with some of the fabric around them. */
  let own = 0;
  for (const host of hosts) {
    const b = boxOf(host);
    if (b !== null) own = Math.max(own, Math.hypot(b.half[0], b.half[1], b.half[2]));
  }
  const centre = new Vector3();
  for (const v of subject) centre.add(v);
  centre.divideScalar(subject.length);
  const floor = own * CONTEXT_RADII;
  for (const [axis, sign] of [[right, 1], [right, -1], [up, 1], [up, -1]] as const) {
    points.push(centre.clone().addScaledVector(axis, sign * floor));
  }
  return framePointsFromCurrentView(camera, currentTarget, points, TRACE_MARGIN, room);
}
