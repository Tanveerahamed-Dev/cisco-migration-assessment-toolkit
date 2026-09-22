/**
 * camera.ts — a constrained orbit, an eased move, and a depth range that is re-fitted every frame.
 *
 * Three things here are deliberate and each has a failure mode attached:
 *
 *   Constraint. Azimuth is free, polar is clamped to [24, 78] degrees, dolly to a band around the
 *   current framing distance. An unconstrained orbit lets the user end up underneath the fabric or
 *   in a plan view, both of which destroy the tier reading that the whole layout exists to produce.
 *
 *   Near/far re-fitting. design-brief.md §4.1 fixes near at 1.2 for a ~140-unit scene. This scene
 *   spans ~330 units and layout.ts frames it from ~500 away, so a fixed near would either clip the
 *   fabric when the user dollies in or throw away the depth precision that SSAO reads from. The
 *   planes are therefore refitted on EVERY camera change — which is the same fix the brief argues
 *   for (tighten near, do not reach for logarithmicDepthBuffer) with the constant replaced by the
 *   measurement it was standing in for.
 *
 *   Two things that measurement has to be, both learned from a clipped render (C5 audit,
 *   2026-09-21). It has to be taken from what is DRAWN — `measureDrawnBounds` over the live scene
 *   graph — not from the fabric's node sphere: the floor alone is ~1.7x the fabric's span and
 *   reached a view depth of 658 against a far plane of 608.5 at the overview pose. And it has to
 *   run on every change, including the ones OrbitControls applies inside its own wheel handler:
 *   those consume the dolly before the rig's per-frame `controls.update()` runs, which then
 *   reports "no change", so a wheel dolly used to leave the overview's near/far in place — core2
 *   sliced by the near plane at the dolly-in limit, the whole fabric beyond the far plane at the
 *   dolly-out limit.
 *
 *   No drift. There is no idle rotation and no ambient float. A camera that moves on its own makes
 *   a screenshot non-reproducible, and acceptance F6 requires two runs to produce identical
 *   captures.
 */
import { Box3, Matrix4, PerspectiveCamera, Quaternion, Vector3, type Object3D } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { CameraFraming } from "./contract";

const DEG = Math.PI / 180;
/* Not the brief's 12 (design-brief.md §4.1). Measured at the 12-degree top of the clamp (render
   audit, real GPU): core1 overlapped access15, the AP-floor1 label sat on a switch chassis and
   several labels collided — the tier reading the clamp exists to protect was already gone. That
   audit set 28.
   24, not 28 (C5 audit, 2026-09-21): the home view is the layout's 32 degrees, and at a 28 clamp a
   400 px downward drag moved core1 by 9 px and stopped — the default sat at the limit of the one
   gesture that steepens the view. 24 gives that gesture 8 degrees; the label collisions that
   ruled out 12 are a property of the top of the range, which 24 stays well below. */
const MIN_POLAR = 24 * DEG;
const MAX_POLAR = 78 * DEG;
const DOLLY_IN = 0.55;
const DOLLY_OUT = 2.4;

/**
 * NEVER UNDER THE FABRIC, measured in WORLD height rather than in angle (design-brief §4.1).
 *
 * The polar clamp above is an angle about the ORBIT TARGET, and the target moves: a device focus
 * puts it on the focused device. MEASURED (C5 audit, 2026-09-22, both tiers): focusDevice('AP-floor1')
 * — the lowest tier — then a drag to the 78-degree limit put the eye BELOW the access tier, and the
 * frame showed that tier's chassis undersides with their pads and state rings hanging in mid-air,
 * the "objects float" tell. The angle was legal; the height was not.
 *
 * So every rendered pose also satisfies a height rule: the eye LOOKS DOWN on the lid of every
 * chassis that is in view, by at least `EYE_LOOK_DOWN` (and never less than `EYE_ABOVE_VISIBLE_TOP`
 * world units above it). Merely "above" is not enough: a first cut at 2 units put the eye level
 * with the access row, and a chassis seen edge-on at its own lid height still reads as a stack
 * seen from beneath. Where the pose breaks the rule the rig is tilted up rigidly about the zoom
 * anchor (the focused device, while it is on screen) or else the orbit target — `raiseRigAbout` —
 * never steeper than MIN_POLAR, so the device being studied stays where it is in the frame. A
 * chassis out of view does not constrain the eye, so a close look at a low device is not forced
 * up to the top tier.
 */
const EYE_ABOVE_VISIBLE_TOP = 2;
const EYE_LOOK_DOWN = 7 * DEG;
/** A chassis whose lid projects within this NDC margin of the frame counts as in view. */
const EYE_FLOOR_VIEW_MARGIN = 1.1;

/**
 * THE DOLLY FLOOR FOR A FOCUSED DEVICE: close enough to read the chassis itself.
 *
 * The band's inner limit was 0.55 of the CURRENT framing distance, and a device focus frames the
 * device PLUS its whole neighbourhood. MEASURED (C5 audit, 2026-09-22, 1600x900, DPR 1): after 25
 * wheel-ins on access16 the subject was ~110 px wide — the lid grille and the port row collapsed
 * into flat grey blocks that only resolve at DPR 2. The geometry has the detail; the camera could
 * not get to it. With a single device focused, the floor is instead the distance at which the
 * device's own bounding sphere fills `SUBJECT_FILL` of the vertical field of view.
 */
const SUBJECT_FILL = 0.55;

/**
 * Padding around the fabric's bounding sphere at the overview pose. 1.06 fills the stage without
 * letting an edge node touch the frame; the layout's own 1.15 was computed against a declared 16:9
 * and, replayed into a narrower stage, reads as a small drawing on a large canvas.
 */
const HOME_MARGIN = 1.06;

/**
 * The part of the stage the FRAMING may use, as insets in CSS pixels from each canvas edge.
 *
 * MEASURED (C5 audit, 1600x900, both tiers): the overview put core1 at y = 32 of 900 and its name
 * at y ~ 15; on the trace view the "delivered here" chip sat on core1's chassis and core2's name
 * ran under the Quality chip. Every framing fitted the fabric's WORLD bounds to the WHOLE canvas —
 * but the canvas is not all stage. The toolbar (Quality / Reset view / Fabric list) floats over its
 * top band, every device's name is lifted ~1.2 label heights ABOVE its chassis, and the Legend
 * button floats over the bottom-left. A top-tier chassis fitted flush to the canvas edge therefore
 * has nowhere to put its name, so the label layer flips it down onto the chassis and the toolbar
 * covers the rest. The inset is what the framing must leave for those, and it applies to every
 * pose this module computes (home, device focus, trace) — not one call site's special case.
 */
export const FRAME_SAFE_INSET_PX = Object.freeze({ top: 76, bottom: 40, left: 24, right: 24 });
/** Never let the insets eat more than this fraction of an axis on a very small stage. */
const MAX_INSET_FRACTION = 0.3;

/**
 * Head-room the home view keeps inside the polar clamp, so both tilt directions answer from the
 * default (see MIN_POLAR). With the layout's 32-degree view and a 24-degree clamp this is a no-op
 * today; it is the guard that keeps a future view direction or clamp from re-creating the fault.
 */
const HOME_POLAR_HEADROOM = 8 * DEG;

/** Insets as fractions of the viewport, keyed by camera: set by the rig, read by every framing. */
const safeFrameByCamera = new WeakMap<PerspectiveCamera, SafeFrame>();

/** Fractions of the viewport the framing must keep clear, per edge. */
export interface SafeFrame {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/**
 * CSS pixels of the stage covered by an OPEN overlay panel, per edge, measured from the canvas edge.
 *
 * The fixed insets above cover chrome that is always there. A panel the reader opens is not: with
 * the Fabric list open, Reset view still framed the fabric against the whole canvas, so core1 sat
 * under the panel and the off-view pointer fired on the view Reset had just produced. The occlusion
 * is reported by the component that owns the panels (Fabric3D.tsx) and added to the fixed insets.
 */
export interface StageOcclusionPx {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** With an open panel the stage may legitimately lose more than the chrome cap, but never all of it. */
const MAX_OCCLUDED_FRACTION = 0.65;

/** The safe frame for a viewport of the given CSS size. Pure; exported for the tests. */
export function safeFrameFor(width: number, height: number, occlusion: StageOcclusionPx | null = null): SafeFrame {
  const w = Math.max(1, width);
  const h = Math.max(1, height);
  const fit = (a: number, b: number, span: number): [number, number] => {
    const total = (a + b) / span;
    const k = total > MAX_INSET_FRACTION ? MAX_INSET_FRACTION / total : 1;
    return [(a / span) * k, (b / span) * k];
  };
  const [top0, bottom0] = fit(FRAME_SAFE_INSET_PX.top, FRAME_SAFE_INSET_PX.bottom, h);
  const [left0, right0] = fit(FRAME_SAFE_INSET_PX.left, FRAME_SAFE_INSET_PX.right, w);
  if (occlusion === null) return { top: top0, bottom: bottom0, left: left0, right: right0 };
  /* An edge a panel covers keeps the larger of the two: the chrome inset is measured from the
     canvas edge too, so a panel wider than it already contains it. The panel side gets the same
     breathing gap the chrome side has, so no chassis is framed flush against the panel's border. */
  const gap = FRAME_SAFE_INSET_PX.left;
  const widen = (base: number, px: number, span: number): number => (px > 0 ? Math.max(base, (px + gap) / span) : base);
  const cap = (a: number, b: number): [number, number] => {
    const total = a + b;
    const k = total > MAX_OCCLUDED_FRACTION ? MAX_OCCLUDED_FRACTION / total : 1;
    return [a * k, b * k];
  };
  const [top, bottom] = cap(widen(top0, occlusion.top, h), widen(bottom0, occlusion.bottom, h));
  const [left, right] = cap(widen(left0, occlusion.left, w), widen(right0, occlusion.right, w));
  return { top, bottom, left, right };
}

/** Occlusion per canvas, and the rig listening on that canvas. Canvas-keyed so the scene contract
    need not change: a rig is created on exactly one canvas, and so is the component that owns the panels. */
const occlusionByCanvas = new WeakMap<HTMLCanvasElement, StageOcclusionPx | null>();
const occlusionListeners = new WeakMap<HTMLCanvasElement, () => void>();

/**
 * Report the stage area covered by open overlay panels on `canvas`. Takes effect on the NEXT framing
 * (Reset view, Home, a device focus); it does not move the camera by itself, because opening a list
 * is not a request to move the view.
 */
export function setStageOcclusion(canvas: HTMLCanvasElement, occlusion: StageOcclusionPx | null): void {
  occlusionByCanvas.set(canvas, occlusion);
  occlusionListeners.get(canvas)?.();
}

const NO_INSET: SafeFrame = { top: 0, bottom: 0, left: 0, right: 0 };

const _fitCam = new PerspectiveCamera();
const _fitP = new Vector3();
const _fitShift = new Vector3();
const _fitR = new Vector3();
const _fitU = new Vector3();

/**
 * Fit `points` inside the safe frame, looking along `dirFromTarget` (target → eye, unit).
 *
 * Solved in screen space with a real projection rather than in world space, because the safe frame
 * is asymmetric: the camera has to be both far enough away AND offset so that the points' projected
 * extent is centred in the safe band rather than in the canvas. For a candidate distance, the
 * vertical/horizontal offset is solved by a few fixed-point steps (projection is nearly linear in
 * it); the distance is then found by bisection on "the projected span fits the band".
 */
export function fitPointsInSafeFrame(
  points: readonly Vector3[],
  center: Vector3,
  dirFromTarget: Vector3,
  fovDeg: number,
  aspect: number,
  safe: SafeFrame,
  margin: number,
): CameraTarget {
  _fitCam.fov = fovDeg;
  _fitCam.aspect = aspect;
  _fitCam.near = 0.01;
  _fitCam.far = 1e7;
  _fitCam.updateProjectionMatrix();
  _fitR.crossVectors(WORLD_UP, dirFromTarget);
  if (_fitR.lengthSq() < 1e-8) _fitR.set(1, 0, 0);
  _fitR.normalize();
  _fitU.crossVectors(dirFromTarget, _fitR).normalize();
  // NDC band. y: [-1 + 2b, 1 - 2t]; x: [-1 + 2l, 1 - 2r].
  const yLo = -1 + 2 * safe.bottom;
  const yHi = 1 - 2 * safe.top;
  const xLo = -1 + 2 * safe.left;
  const xHi = 1 - 2 * safe.right;
  const tanV = Math.tan((fovDeg * DEG) / 2);
  const tanH = tanV * aspect;

  let sx = 0;
  let sy = 0;
  const place = (d: number): { x0: number; x1: number; y0: number; y1: number } => {
    const tx = center.x + _fitR.x * sx + _fitU.x * sy;
    const ty = center.y + _fitR.y * sx + _fitU.y * sy;
    const tz = center.z + _fitR.z * sx + _fitU.z * sy;
    _fitCam.position.set(tx + dirFromTarget.x * d, ty + dirFromTarget.y * d, tz + dirFromTarget.z * d);
    _fitCam.up.set(0, 1, 0);
    _fitCam.lookAt(tx, ty, tz);
    _fitCam.updateMatrixWorld();
    let x0 = Infinity;
    let x1 = -Infinity;
    let y0 = Infinity;
    let y1 = -Infinity;
    for (const p of points) {
      _fitP.copy(p).project(_fitCam);
      x0 = Math.min(x0, _fitP.x);
      x1 = Math.max(x1, _fitP.x);
      y0 = Math.min(y0, _fitP.y);
      y1 = Math.max(y1, _fitP.y);
    }
    return { x0, x1, y0, y1 };
  };
  const centre = (d: number): { x0: number; x1: number; y0: number; y1: number } => {
    let e = place(d);
    for (let k = 0; k < 4; k += 1) {
      // Move the look-at point so the projected extent's midpoint lands on the band's midpoint.
      // One NDC unit at distance d is d * tan(half-fov) world units along that axis.
      sx += (((e.x0 + e.x1) / 2 - (xLo + xHi) / 2) * d * tanH);
      sy += (((e.y0 + e.y1) / 2 - (yLo + yHi) / 2) * d * tanV);
      e = place(d);
    }
    return e;
  };
  const fits = (d: number): boolean => {
    const e = centre(d);
    return (
      (e.x1 - e.x0) * margin <= xHi - xLo &&
      (e.y1 - e.y0) * margin <= yHi - yLo &&
      e.x0 >= -1.5 &&
      e.y0 >= -1.5
    );
  };
  // Bracket: grow until it fits, then bisect.
  let radius = 0;
  for (const p of points) radius = Math.max(radius, p.distanceTo(center));
  let lo = Math.max(1e-3, radius * 0.05);
  let hi = Math.max(1, radius * 2);
  for (let i = 0; i < 40 && !fits(hi); i += 1) {
    lo = hi;
    hi *= 1.6;
  }
  for (let i = 0; i < 32; i += 1) {
    const mid = (lo + hi) / 2;
    if (fits(mid)) hi = mid;
    else lo = mid;
  }
  centre(hi);
  _fitShift.copy(center).addScaledVector(_fitR, sx).addScaledVector(_fitU, sy);
  return {
    position: [
      _fitShift.x + dirFromTarget.x * hi,
      _fitShift.y + dirFromTarget.y * hi,
      _fitShift.z + dirFromTarget.z * hi,
    ],
    target: [_fitShift.x, _fitShift.y, _fitShift.z],
  };
}

/** Clamp a target→eye direction's polar angle into [lo, hi] radians, keeping its azimuth. */
export function clampPolar(dir: Vector3, lo: number, hi: number): Vector3 {
  const polar = Math.acos(Math.min(1, Math.max(-1, dir.y / Math.max(1e-9, dir.length()))));
  const p = Math.min(hi, Math.max(lo, polar));
  if (p === polar) return dir.normalize();
  const h = Math.hypot(dir.x, dir.z);
  const ax = h < 1e-9 ? 0 : dir.x / h;
  const az = h < 1e-9 ? 1 : dir.z / h;
  return dir.set(ax * Math.sin(p), Math.cos(p), az * Math.sin(p));
}

/** design-brief.md §4.8: the one deliberate motion longer than 300 ms in the entire product. */
export const CAMERA_TWEEN_MS = 620;

export interface CameraTarget {
  position: [number, number, number];
  target: [number, number, number];
}

export interface CameraRigOptions {
  framing: CameraFraming & { fovDeg?: number };
  /** Scene bounding sphere; the depth range is fitted to it. */
  sphere: { center: [number, number, number]; radius: number };
  /** Axis-aligned bounds, for an exact overview fit. Optional: the sphere is the fallback. */
  box?: { min: [number, number, number]; max: [number, number, number] };
  /**
   * Bounds of everything the scene DRAWS (floor, decks, cable arcs included); the depth range is
   * fitted to it. Optional because the scene graph is built after the rig — supply it with
   * `setDepthBounds` as soon as it exists. Until then the sphere stands in.
   */
  depthBox?: Bounds3 | null;
  reducedMotion: boolean;
  width: number;
  height: number;
}

export interface Bounds3 {
  min: [number, number, number];
  max: [number, number, number];
  /**
   * The individual boxes the union was made from, six numbers each (min xyz, max xyz). When
   * present the depth range is fitted to THESE: the union of a wide flat floor and a tall narrow
   * fabric has corners — floor-edge x fabric-top — that no geometry occupies, and fitting to them
   * pulls near toward the camera for nothing.
   */
  parts?: Float64Array;
}

export interface CameraRig {
  camera: PerspectiveCamera;
  controls: OrbitControls;
  /** True while an eased move is in flight. */
  isTweening(): boolean;
  /** Ease (or jump, under reduced motion) to a pose. Clears any zoom anchor. */
  moveTo(target: CameraTarget, opts?: { immediate?: boolean }): void;
  /**
   * The world point a wheel dolly zooms TOWARD, or null for OrbitControls' own dolly toward the
   * orbit target. Set by a device focus, cleared by any other camera move. `subjectRadius`, when
   * given, is the focused device's own bounding radius: the dolly floor becomes the distance that
   * frames THAT (see SUBJECT_FILL), not a fraction of the neighbourhood framing.
   */
  setZoomAnchor(point: [number, number, number] | null, subjectRadius?: number): void;
  /**
   * The lid of every chassis, three numbers each (x, top y, z). Every pose keeps the eye above
   * the lids that are in view (see EYE_ABOVE_VISIBLE_TOP). null = no height rule.
   */
  setEyeFloor(lids: Float32Array | null): void;
  /** The pose `resetCamera()` returns to; replaced when the data changes. */
  setHomeFraming(
    framing: CameraFraming,
    sphere: { center: [number, number, number]; radius: number },
    box?: { min: [number, number, number]; max: [number, number, number] },
  ): void;
  home(opts?: { immediate?: boolean }): void;
  /** The drawn-geometry bounds the near/far planes must enclose; see `measureDrawnBounds`. */
  setDepthBounds(box: Bounds3 | null): void;
  setViewport(width: number, height: number): void;
  setReducedMotion(reduced: boolean): void;
  /**
   * Orbit exactly as a PRIMARY-button pointer drag of (dx, dy) CSS pixels would: the keyboard
   * equivalent of the drag (acceptance D1). It drives OrbitControls' own drag handlers, so the pose,
   * the polar/distance clamps, the damping tail and the "start"/"change"/"end" events are the
   * pointer's — there is no second camera model to drift from the first.
   */
  orbitBy(dxPx: number, dyPx: number): void;
  /** Pan exactly as a SECONDARY-button pointer drag of (dx, dy) CSS pixels would. See orbitBy. */
  panBy(dxPx: number, dyPx: number): void;
  /** Advance damping and any tween. Returns true when the camera moved this frame. */
  update(nowMs: number): boolean;
  dispose(): void;
}

/**
 * `cubic-bezier(0.16, 1, 0.3, 1)` — the same curve as `--ease-out` in tokens.css, so a camera move
 * and a panel opening next to it share one motion character. Solved by Newton's method with a
 * bisection fallback; the curve is monotonic in x, so this converges in a handful of steps.
 */
function easeOutExpoBezier(t: number): number {
  const x1 = 0.16;
  const y1 = 1;
  const x2 = 0.3;
  const y2 = 1;
  const bez = (a: number, b: number, u: number): number => {
    const v = 1 - u;
    return 3 * v * v * u * a + 3 * v * u * u * b + u * u * u;
  };
  const slope = (a: number, b: number, u: number): number => {
    const v = 1 - u;
    return 3 * v * v * (a - 0) + 6 * v * u * (b - a) + 3 * u * u * (1 - b);
  };
  let u = t;
  for (let i = 0; i < 6; i += 1) {
    const x = bez(x1, x2, u) - t;
    if (Math.abs(x) < 1e-5) break;
    const d = slope(x1, x2, u);
    if (Math.abs(d) < 1e-6) break;
    u -= x / d;
  }
  return bez(y1, y2, Math.min(1, Math.max(0, u)));
}

const _v = new Vector3();
const _prevPos = new Vector3();
const _prevTarget = new Vector3();
const _prevQuat = new Quaternion();
/** Squared world units (and the matching small-angle term): OrbitControls' own EPS, 1e-6. */
const POSE_EPS = 1e-6;
const _fromPos = new Vector3();
const _fromTarget = new Vector3();
const _toPos = new Vector3();
const _toTarget = new Vector3();
const _sphereCenter = new Vector3();
const _forward = new Vector3();
const _right = new Vector3();
const _up = new Vector3();
const _corner = new Vector3();
const _depthFwd = new Vector3();
const _depthCorner = new Vector3();
const WORLD_UP = new Vector3(0, 1, 0);

type WithGeometry = Object3D & {
  geometry?: { boundingBox: Box3 | null; computeBoundingBox(): void };
  isInstancedMesh?: boolean;
  count?: number;
  getMatrixAt?(index: number, out: Matrix4): void;
};

/**
 * World-space axis-aligned bounds of every drawable object under `root` — meshes, each instance of
 * an instanced mesh, fat-line cable batches and plain lines.
 *
 * This is what the depth range is fitted to, and it is measured rather than derived from the layout
 * on purpose: the floor, the tier decks and the cable sag are each sized by their own module, and a
 * depth range computed from a restated copy of those rules is a cache that silently stops enclosing
 * what it describes the day one of them changes. Invisible objects are included — a hover shell or
 * halo that becomes visible must not be clipped on its first frame. Null for an empty scene.
 */
export function measureDrawnBounds(root: Object3D): Bounds3 | null {
  const total = new Box3();
  const local = new Box3();
  const m = new Matrix4();
  const inst = new Matrix4();
  const parts: number[] = [];
  const add = (b: Box3): void => {
    total.union(b);
    parts.push(b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z);
  };
  root.updateMatrixWorld(true);
  root.traverse((node) => {
    const o = node as WithGeometry;
    const g = o.geometry;
    if (g === undefined || typeof g.computeBoundingBox !== "function") return;
    g.computeBoundingBox();
    const bb = g.boundingBox;
    if (bb === null || bb.isEmpty() || !Number.isFinite(bb.min.x) || !Number.isFinite(bb.max.x)) return;
    if (o.isInstancedMesh === true && typeof o.getMatrixAt === "function") {
      const n = o.count ?? 0;
      for (let i = 0; i < n; i += 1) {
        o.getMatrixAt(i, inst);
        m.multiplyMatrices(o.matrixWorld, inst);
        add(local.copy(bb).applyMatrix4(m));
      }
      return;
    }
    add(local.copy(bb).applyMatrix4(o.matrixWorld));
  });
  if (total.isEmpty()) return null;
  return {
    min: [total.min.x, total.min.y, total.min.z],
    max: [total.max.x, total.max.y, total.max.z],
    parts: Float64Array.from(parts),
  };
}

/** The drag handlers OrbitControls' pointer listeners call (three 0.186 OrbitControls.js). */
interface OrbitDragHandlers {
  _handleMouseDownRotate(e: { clientX: number; clientY: number }): void;
  _handleMouseMoveRotate(e: { clientX: number; clientY: number }): void;
  _handleMouseDownPan(e: { clientX: number; clientY: number }): void;
  _handleMouseMovePan(e: { clientX: number; clientY: number }): void;
}

export function createCameraRig(
  canvas: HTMLCanvasElement,
  opts: CameraRigOptions,
): CameraRig {
  const fov = opts.framing.fovDeg ?? 45;
  const camera = new PerspectiveCamera(fov, opts.width / Math.max(1, opts.height), 1, 1000);
  camera.position.set(...opts.framing.position);

  const controls = new OrbitControls(camera, canvas);
  controls.target.set(...opts.framing.target);
  /* Damping is inertia: the view keeps moving after the hand (or key) stops. Under reduced motion
     every move lands whole, pointer and keyboard alike (design-brief.md §4.8); see setReducedMotion. */
  controls.enableDamping = !opts.reducedMotion;
  controls.dampingFactor = 0.085;
  controls.enablePan = true;
  controls.screenSpacePanning = false;
  controls.rotateSpeed = 0.75;
  controls.zoomSpeed = 0.9;
  controls.panSpeed = 0.7;
  controls.minPolarAngle = MIN_POLAR;
  controls.maxPolarAngle = MAX_POLAR;
  // Explicit, not merely default: a camera that orbits by itself is on the brief's list of
  // cheap-render tells, and it would make every capture a different image.
  controls.autoRotate = false;

  let sphereRadius = Math.max(1, opts.sphere.radius);
  _sphereCenter.set(...opts.sphere.center);
  /**
   * Home is stored as a DIRECTION plus a sphere, not as a fixed position.
   *
   * `layout.framing` computes its distance for a declared 16:9 aspect. The stage is 758 px wide at
   * the 1440 layout and 1158 at 1920 — neither is 16:9 — so replaying the stored position leaves
   * the fabric small in a narrow viewport and clipped in a wide one. Keeping the layout's view
   * DIRECTION (which is the part that carries the design intent) and re-fitting the distance to the
   * viewport actually in front of the user gives the same composition at every size.
   */
  const homeDirection = new Vector3(
    opts.framing.position[0] - opts.framing.target[0],
    opts.framing.position[1] - opts.framing.target[1],
    opts.framing.position[2] - opts.framing.target[2],
  ).normalize();
  clampPolar(homeDirection, MIN_POLAR + HOME_POLAR_HEADROOM, MAX_POLAR - HOME_POLAR_HEADROOM);
  let homeBox: { min: [number, number, number]; max: [number, number, number] } | null =
    opts.box ?? null;
  let reducedMotion = opts.reducedMotion;
  let depthBox: Bounds3 | null = opts.depthBox ?? null;
  let viewW = opts.width;
  let viewH = opts.height;
  const refreshSafeFrame = (): void => {
    safeFrameByCamera.set(camera, safeFrameFor(viewW, viewH, occlusionByCanvas.get(canvas) ?? null));
  };
  refreshSafeFrame();
  occlusionListeners.set(canvas, refreshSafeFrame);

  const homePose = (): CameraTarget => {
    if (homeBox !== null) {
      const corners: Vector3[] = [];
      for (let i = 0; i < 8; i += 1) {
        corners.push(
          new Vector3(
            (i & 1) === 0 ? homeBox.min[0] : homeBox.max[0],
            (i & 2) === 0 ? homeBox.min[1] : homeBox.max[1],
            (i & 4) === 0 ? homeBox.min[2] : homeBox.max[2],
          ),
        );
      }
      return fitPointsInSafeFrame(
        corners,
        _sphereCenter,
        homeDirection,
        camera.fov,
        camera.aspect,
        safeFrameByCamera.get(camera) ?? NO_INSET,
        // The safe frame IS the padding here; HOME_MARGIN on top of it padded twice and shrank the
        // fabric enough to crowd the access-tier labels into each other. It remains the margin
        // for the sphere fallback below, which has no safe frame to lean on.
        1.0,
      );
    }
    const dist = fitDistance();
    return {
      position: [
        _sphereCenter.x + homeDirection.x * dist,
        _sphereCenter.y + homeDirection.y * dist,
        _sphereCenter.z + homeDirection.z * dist,
      ],
      target: [_sphereCenter.x, _sphereCenter.y, _sphereCenter.z],
    };
  };

  /**
   * Distance that fits the fabric's bounding BOX, not its bounding sphere.
   *
   * The fabric is a flat slab — 322 x 133 x 83 world units — so its bounding sphere has radius 166
   * while its silhouette from the design view direction is far smaller than that. Framing the
   * sphere therefore wastes a third of the stage on empty backdrop, and at the stage's real aspect
   * that reads as a small diagram on a large canvas. Fitting the eight corners through the actual
   * frustum is exact and gives the composition the brief is asking for.
   *
   * Falls back to the sphere when no box was supplied, so a caller that only has a radius still
   * gets a correct (if looser) frame rather than a wrong one.
   */
  function fitDistance(): number {
    const vFov = camera.fov * DEG;
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
    const tanV = Math.tan(vFov / 2);
    const tanH = Math.tan(hFov / 2);
    if (homeBox === null) {
      return (sphereRadius * HOME_MARGIN) / Math.sin(Math.min(vFov, hFov) / 2);
    }
    // View basis for the home direction: forward points from the camera toward the centre.
    _forward.copy(homeDirection).multiplyScalar(-1);
    _right.crossVectors(_forward, WORLD_UP);
    if (_right.lengthSq() < 1e-8) _right.set(1, 0, 0);
    _right.normalize();
    _up.crossVectors(_right, _forward).normalize();

    let needed = 0;
    for (let i = 0; i < 8; i += 1) {
      _corner.set(
        (i & 1) === 0 ? homeBox.min[0] : homeBox.max[0],
        (i & 2) === 0 ? homeBox.min[1] : homeBox.max[1],
        (i & 4) === 0 ? homeBox.min[2] : homeBox.max[2],
      );
      _corner.sub(_sphereCenter);
      const x = Math.abs(_corner.dot(_right)) * HOME_MARGIN;
      const y = Math.abs(_corner.dot(_up)) * HOME_MARGIN;
      // Depth along forward, positive when the corner is BEHIND the centre and therefore needs
      // less distance; a near corner needs more.
      const z = _corner.dot(_forward);
      needed = Math.max(needed, x / tanH - z, y / tanV - z);
    }
    return Math.max(needed, sphereRadius * 0.4);
  }

  let tweenStart = 0;
  let tweenActive = false;

  /** The focused device's own bounding radius, or null when no single device is focused. */
  let subjectRadius: number | null = null;
  const applyDollyBand = (): void => {
    const d = camera.position.distanceTo(controls.target);
    // The band follows the CURRENT framing, not the overview framing. Focusing on one device puts
    // the camera far inside the overview's inner limit; a fixed band would then either refuse to
    // zoom in at all or refuse to pull back out.
    const inner =
      subjectRadius !== null
        ? subjectFloorDistance(subjectRadius, camera.fov)
        : Math.max(sphereRadius * 0.06, d * DOLLY_IN);
    controls.minDistance = Math.min(d, inner);
    controls.maxDistance = Math.max(d * DOLLY_OUT, sphereRadius * 4);
  };

  let eyeLids: Float32Array | null = null;
  /** Apply the height rule (see EYE_ABOVE_VISIBLE_TOP). True when the eye was moved. */
  const keepEyeAboveVisibleLids = (): boolean => {
    if (eyeLids === null) return false;
    let movedEye = false;
    // Raising the eye tilts the view down, which can only move lids OUT of the top of the frame,
    // and moves it slightly nearer the lids; a few passes settle it.
    for (let pass = 0; pass < 4; pass += 1) {
      camera.updateMatrixWorld();
      const floor = visibleLidFloor(camera, eyeLids);
      if (!(camera.position.y < floor - 1e-6)) break;
      /* Pivot on the zoom anchor while it is on screen: the rig turns rigidly about the device
         the reader zoomed toward, so it stays where it is in the frame. Pivoting on the orbit
         target instead (which a focus biases toward the neighbourhood) slid a low device off the
         bottom of the frame as the lift steepened the view during a zoom. */
      let pivot: Vector3 = controls.target;
      if (zoomAnchor !== null) {
        _v.copy(zoomAnchor).project(camera);
        if (_v.z > -1 && _v.z < 1 && Math.abs(_v.x) <= 1 && Math.abs(_v.y) <= 1) pivot = zoomAnchor;
      }
      if (!raiseRigAbout(camera.position, controls.target, pivot, floor, MIN_POLAR)) break;
      camera.lookAt(controls.target);
      movedEye = true;
    }
    if (movedEye) camera.updateMatrixWorld();
    return movedEye;
  };

  const fittedFor = {
    box: undefined as Bounds3 | null | undefined,
    radius: Number.NaN,
    pos: new Vector3(Number.NaN, 0, 0),
    target: new Vector3(Number.NaN, 0, 0),
  };
  const refitDepth = (): void => {
    // Quantised, then applied unconditionally. A hysteresis band here ("only update past 1 %")
    // makes the projection depend on the PATH the camera took rather than on where it ended up:
    // two runs that reach the same pose through a different number of tween frames end with
    // different near/far and therefore different pixels. Quantising to a fixed grid keeps the
    // update cheap — the value only actually changes when the camera has moved a real distance —
    // while making it a pure function of the current pose, which is what F6 needs.
    // Skipped when nothing it reads has changed — it is now called every frame (see update()).
    if (
      fittedFor.box === depthBox &&
      fittedFor.radius === sphereRadius &&
      fittedFor.pos.equals(camera.position) &&
      fittedFor.target.equals(controls.target)
    ) {
      return;
    }
    fittedFor.box = depthBox;
    fittedFor.radius = sphereRadius;
    fittedFor.pos.copy(camera.position);
    fittedFor.target.copy(controls.target);
    const q = Math.max(0.5, sphereRadius * 0.002);
    let near: number;
    let far: number;
    if (depthBox !== null) {
      // Exact view-depth range of the drawn geometry's box along the CURRENT view axis (target
      // minus position: the camera's matrixWorld can be a frame stale here, the pose cannot). A
      // corner behind the camera means the camera is over the geometry's footprint; near then
      // falls to its floor of 1, which is also what the sphere fit did at close range.
      _depthFwd.copy(controls.target).sub(camera.position);
      if (_depthFwd.lengthSq() < 1e-8) _depthFwd.set(0, 0, -1);
      _depthFwd.normalize();
      let zMin = Infinity;
      let zMax = -Infinity;
      const b = depthBox;
      const parts = b.parts ?? Float64Array.of(...b.min, ...b.max);
      for (let k = 0; k + 5 < parts.length; k += 6) {
        for (let i = 0; i < 8; i += 1) {
          _depthCorner.set(
            parts[k + ((i & 1) === 0 ? 0 : 3)] ?? 0,
            parts[k + ((i & 2) === 0 ? 1 : 4)] ?? 0,
            parts[k + ((i & 4) === 0 ? 2 : 5)] ?? 0,
          );
          const z = _depthCorner.sub(camera.position).dot(_depthFwd);
          if (z < zMin) zMin = z;
          if (z > zMax) zMax = z;
        }
      }
      const pad = Math.max(2, (zMax - zMin) * 0.02);
      near = Math.max(1, Math.floor((zMin - pad) / q) * q);
      far = Math.max(near + 10, Math.ceil((zMax + pad) / q) * q);
    } else {
      const d = camera.position.distanceTo(_sphereCenter);
      near = Math.max(1, Math.round((d - sphereRadius * 1.05) / q) * q);
      far = Math.max(near + 10, Math.round((d + sphereRadius * 1.8) / q) * q);
    }
    if (camera.near !== near || camera.far !== far) {
      camera.near = near;
      camera.far = far;
      camera.updateProjectionMatrix();
    }
  };

  /**
   * Until the user or the app has deliberately moved the camera, the overview pose is re-derived
   * on every viewport change. The alternative is the pose computed against whatever the canvas
   * measured at construction — routinely 1x1, because the element has not been laid out yet — and
   * that pose is then frozen into the first thing the user sees. After any deliberate move this
   * stops: a resize must never undo a camera position somebody chose.
   */
  let userMoved = false;
  controls.addEventListener("start", () => {
    userMoved = true;
  });
  /* OrbitControls applies a wheel dolly (and keyboard pans) inside its own event handler and fires
     "change" from there; the rig's per-frame `controls.update()` then finds nothing left to do and
     returns false. Refitting on the event keeps near/far true for those moves. */
  controls.addEventListener("change", () => refitDepth());

  /* ZOOM TOWARD THE FOCUSED SUBJECT, not toward the orbit target.
   *
   * A focus framing's orbit target is NOT the device: it is biased up to 70 % of the framed radius
   * toward the device's neighbourhood (scene.ts focusFramingFor) and then shifted into the safe
   * frame. OrbitControls dollies along the eye→target axis, so every wheel-in slid the subject
   * away from the point being zoomed toward — MEASURED (C5 critic, reproduced 2026-09-21):
   * focusDevice('AP-floor1') put the AP at y 622 of 900, and twelve wheel-ins at the canvas centre
   * pushed it to y 763, half off the bottom edge with its label crammed against the frame.
   *
   * Zooming about a point P by factor s moves the eye to P + (eye - P)s and the target to
   * P + (target - P)s. OrbitControls has already applied the dolly about the TARGET, which
   * differs from that by the same vector (P - target)(1 - s) for both eye and target — so the
   * correction is one translation, applied after its handler (this listener is registered after
   * OrbitControls' own), which keeps P fixed on screen through the whole zoom. Only while P is on
   * screen: zooming toward a subject the user has panned away from would drag the view back to it. */
  let zoomAnchor: Vector3 | null = null;
  let wheelFromDistance = 0;
  const _wheelTarget = new Vector3();
  /* The pre-dolly state is taken on OrbitControls' own "start" event, which its wheel handler
     dispatches immediately BEFORE applying the dolly. A capture-phase wheel listener would do the
     same in Chrome, but listener order at the target element is not the same in every DOM. */
  const onWheelBefore = (): void => {
    wheelFromDistance = camera.position.distanceTo(controls.target);
    _wheelTarget.copy(controls.target);
  };
  const onWheelAfter = (): void => {
    if (zoomAnchor === null || tweenActive || wheelFromDistance <= 0) return;
    const to = camera.position.distanceTo(controls.target);
    const scale = to / wheelFromDistance;
    if (!(scale > 0) || Math.abs(1 - scale) < 1e-6) return;
    camera.updateMatrixWorld();
    _v.copy(zoomAnchor).project(camera);
    if (!(_v.z > -1 && _v.z < 1 && Math.abs(_v.x) <= 1 && Math.abs(_v.y) <= 1)) return;
    _v.copy(zoomAnchor).sub(_wheelTarget).multiplyScalar(1 - scale);
    camera.position.add(_v);
    controls.target.add(_v);
    camera.updateMatrixWorld();
    refitDepth();
  };
  controls.addEventListener("start", onWheelBefore);
  canvas.addEventListener("wheel", onWheelAfter, { passive: true });

  /**
   * A drag of (dx, dy) CSS pixels, replayed through OrbitControls' OWN mouse-drag handlers — the
   * functions its pointerdown/pointermove listeners call — bracketed by the same "start"/"end"
   * events its pointer handlers dispatch. The handlers are underscore-prefixed in three 0.186 but
   * are the drag path itself: calling the public rotateLeft/pan instead would re-derive the
   * pixels-to-angle formula here, a second model that could drift from the one a mouse uses.
   * camera.keyboard.test.ts pins pose equality against a real pointer drag.
   */
  const dragThroughControls = (kind: "rotate" | "pan", dx: number, dy: number): void => {
    if (!Number.isFinite(dx) || !Number.isFinite(dy) || (dx === 0 && dy === 0)) return;
    const c = controls as unknown as OrbitDragHandlers;
    controls.dispatchEvent({ type: "start" });
    if (kind === "rotate") {
      c._handleMouseDownRotate({ clientX: 0, clientY: 0 });
      c._handleMouseMoveRotate({ clientX: dx, clientY: dy });
    } else {
      c._handleMouseDownPan({ clientX: 0, clientY: 0 });
      c._handleMouseMovePan({ clientX: dx, clientY: dy });
    }
    controls.dispatchEvent({ type: "end" });
  };

  const snapHome = (): void => {
    const pose = homePose();
    camera.position.set(...pose.position);
    controls.target.set(...pose.target);
    camera.updateMatrixWorld();
  };

  snapHome();
  applyDollyBand();
  refitDepth();
  camera.updateMatrixWorld();

  const rig: CameraRig = {
    camera,
    controls,

    isTweening(): boolean {
      return tweenActive;
    },

    moveTo(target: CameraTarget, moveOpts?: { immediate?: boolean }): void {
      userMoved = true;
      zoomAnchor = null;
      subjectRadius = null;
      _toPos.set(...target.position);
      _toTarget.set(...target.target);
      if (moveOpts?.immediate === true || reducedMotion) {
        // Reduced motion JUMPS. The end state is identical to the animated end state — the user
        // loses the movement, never the information (design-brief.md §4.8).
        camera.position.copy(_toPos);
        controls.target.copy(_toTarget);
        tweenActive = false;
        applyDollyBand();
        refitDepth();
        controls.update();
        return;
      }
      _fromPos.copy(camera.position);
      _fromTarget.copy(controls.target);
      tweenStart = 0;
      tweenActive = true;
    },

    setHomeFraming(framing: CameraFraming, sphere, box): void {
      homeBox = box ?? null;
      homeDirection
        .set(
          framing.position[0] - framing.target[0],
          framing.position[1] - framing.target[1],
          framing.position[2] - framing.target[2],
        )
        .normalize();
      clampPolar(homeDirection, MIN_POLAR + HOME_POLAR_HEADROOM, MAX_POLAR - HOME_POLAR_HEADROOM);
      sphereRadius = Math.max(1, sphere.radius);
      _sphereCenter.set(...sphere.center);
      applyDollyBand();
      refitDepth();
    },

    setZoomAnchor(point: [number, number, number] | null, radius?: number): void {
      zoomAnchor = point === null ? null : new Vector3(...point);
      subjectRadius = point !== null && radius !== undefined && radius > 0 ? radius : null;
      // An immediate move has already applied its band; a tween applies it when it lands.
      if (!tweenActive) applyDollyBand();
    },

    setEyeFloor(lids: Float32Array | null): void {
      eyeLids = lids !== null && lids.length >= 3 ? lids : null;
    },

    home(homeOpts?: { immediate?: boolean }): void {
      rig.moveTo(homePose(), homeOpts);
    },

    setDepthBounds(box: Bounds3 | null): void {
      depthBox = box;
      refitDepth();
    },

    setViewport(width: number, height: number): void {
      camera.aspect = width / Math.max(1, height);
      camera.updateProjectionMatrix();
      viewW = width;
      viewH = height;
      refreshSafeFrame();
      if (!userMoved && !tweenActive) {
        snapHome();
        applyDollyBand();
        refitDepth();
      }
    },

    setReducedMotion(reduced: boolean): void {
      reducedMotion = reduced;
      controls.enableDamping = !reduced;
      if (reduced && tweenActive) {
        camera.position.copy(_toPos);
        controls.target.copy(_toTarget);
        tweenActive = false;
        controls.update();
      }
    },

    update(nowMs: number): boolean {
      let moved = false;
      if (tweenActive) {
        if (tweenStart === 0) tweenStart = nowMs;
        const raw = Math.min(1, (nowMs - tweenStart) / CAMERA_TWEEN_MS);
        const k = easeOutExpoBezier(raw);
        camera.position.copy(_fromPos).lerp(_toPos, k);
        _v.copy(_fromTarget).lerp(_toTarget, k);
        controls.target.copy(_v);
        moved = true;
        if (raw >= 1) {
          tweenActive = false;
          applyDollyBand();
        }
      }
      // OrbitControls reports whether damping or input actually changed the camera this frame;
      // that boolean is what lets the render loop go idle instead of spinning on a still scene.
      /* ...except at a dolly limit, where it reports a change that never happens. Its update()
         returns true on `zoomChanged = prevRadius != clampDistance(radius * scale)`, and with the
         camera parked AT minDistance the radius it recomputes from the position differs from
         minDistance by a rounding error every frame — so the clamp "changes" it, forever, while
         the pose is bit-for-bit still. MEASURED (C6 critic, reproduced 2026-09-21 in the app on a
         traced flow): six wheel-ins to the limit, then 60 rendered frames a second for as long as
         anyone watched, `converged` false throughout, the canvas pixel-static. The render loop
         now asks the pose itself: a report with no measurable motion is not a move. */
      _prevPos.copy(camera.position);
      _prevTarget.copy(controls.target);
      _prevQuat.copy(camera.quaternion);
      /* The height rule runs on EVERY pose — a user orbit, a damping tail, a tween frame — after
         OrbitControls has applied its own clamps. A pose it corrects back to where it already was
         (a drag held against the limit) is judged still by the pose comparison below. */
      const reported = controls.update();
      const lifted = keepEyeAboveVisibleLids();
      if (reported || lifted) {
        const still =
          _prevPos.distanceToSquared(camera.position) < POSE_EPS &&
          _prevTarget.distanceToSquared(controls.target) < POSE_EPS &&
          8 * (1 - Math.abs(_prevQuat.dot(camera.quaternion))) < POSE_EPS;
        if (!still) moved = true;
        else {
          /* And stop the phantom at its source: it also fires OrbitControls' "change" event, which
             the scene treats as a camera move (scene.ts onCameraChange -> markDirty). Widening the
             band by a hair to include the pose the camera is actually parked at makes the clamp an
             identity, so the next update() reports nothing. The limit itself is unchanged. */
          const d = camera.position.distanceTo(controls.target);
          controls.minDistance = Math.min(controls.minDistance, d * (1 - 1e-9));
          controls.maxDistance = Math.max(controls.maxDistance, d * (1 + 1e-9));
        }
      }
      // Unconditional and cheap: a no-op unless the quantised pair actually changed. Gating it on
      // `moved` is how a wheel dolly — already applied, so `update()` reports false — kept a
      // stale depth range (see the header).
      refitDepth();
      return moved;
    },

    orbitBy(dxPx: number, dyPx: number): void {
      if (!controls.enabled || !controls.enableRotate) return;
      dragThroughControls("rotate", dxPx, dyPx);
    },

    panBy(dxPx: number, dyPx: number): void {
      if (!controls.enabled || !controls.enablePan) return;
      dragThroughControls("pan", dxPx, dyPx);
    },

    dispose(): void {
      controls.removeEventListener("start", onWheelBefore);
      canvas.removeEventListener("wheel", onWheelAfter);
      controls.dispose();
    },
  };

  return rig;
}

/**
 * Frame a bounding sphere from the current view direction.
 *
 * Used for the trace re-framing, where there is no precomputed framing to hand: the camera keeps
 * the direction the user is already looking from and only changes distance and centre. Changing
 * the view direction under the user because a trace arrived would be exactly the "selection
 * restarts rather than re-aims" failure the product is built to avoid.
 */
export function frameSphereFromCurrentView(
  camera: PerspectiveCamera,
  currentTarget: Vector3,
  center: Vector3,
  radius: number,
  margin = 1.25,
): CameraTarget {
  _v.copy(camera.position).sub(currentTarget);
  if (_v.lengthSq() < 1e-6) _v.set(0, 1, 1);
  _v.normalize();
  /* Fitted through the same safe frame as the overview (FRAME_SAFE_INSET_PX), so a focused device
     or a traced path is centred in the part of the stage the toolbar, the labels and the Legend
     leave free — not in the canvas. The sphere is sampled on its six screen/depth axis points; the
     margin is the caller's, applied to the projected span. */
  const r = Math.max(radius, 1);
  const right = new Vector3().crossVectors(WORLD_UP, _v);
  if (right.lengthSq() < 1e-8) right.set(1, 0, 0);
  right.normalize();
  const up = new Vector3().crossVectors(_v, right).normalize();
  const pts = [
    center.clone().addScaledVector(right, r),
    center.clone().addScaledVector(right, -r),
    center.clone().addScaledVector(up, r),
    center.clone().addScaledVector(up, -r),
    center.clone().addScaledVector(_v, r),
    center.clone().addScaledVector(_v, -r),
  ];
  return fitPointsInSafeFrame(
    pts,
    center,
    _v.clone(),
    camera.fov,
    camera.aspect,
    safeFrameByCamera.get(camera) ?? NO_INSET,
    margin,
  );
}

/**
 * The lowest eye height that looks DOWN on every lid in view: for each lid among `lids` (x, top y,
 * z triples) that projects into the camera's view, lid y + max(EYE_ABOVE_VISIBLE_TOP,
 * tan(EYE_LOOK_DOWN) x its horizontal distance from the eye). -Infinity when no lid is in view.
 * The camera's world matrix must be current.
 */
export function visibleLidFloor(camera: PerspectiveCamera, lids: Float32Array): number {
  let floor = Number.NEGATIVE_INFINITY;
  const slope = Math.tan(EYE_LOOK_DOWN);
  const ex = camera.position.x;
  const ez = camera.position.z;
  for (let k = 0; k + 2 < lids.length; k += 3) {
    const x = lids[k] ?? 0;
    const y = lids[k + 1] ?? 0;
    const z = lids[k + 2] ?? 0;
    const need = y + Math.max(EYE_ABOVE_VISIBLE_TOP, slope * Math.hypot(x - ex, z - ez));
    if (need <= floor) continue;
    _lid.set(x, y, z).project(camera);
    if (_lid.z > -1 && _lid.z < 1 && Math.abs(_lid.x) <= EYE_FLOOR_VIEW_MARGIN && Math.abs(_lid.y) <= EYE_FLOOR_VIEW_MARGIN) {
      floor = need;
    }
  }
  return floor;
}

/**
 * Tilt the whole rig (eye AND target) rigidly upward about a horizontal axis through `pivot` — the
 * axis perpendicular to the view's azimuth — until eye.y >= `minY`, never steeper than `minPolar`.
 * A rigid rotation keeps `pivot` exactly where it was on screen; with `pivot` = `target` it is an
 * ordinary orbit (distance and azimuth kept, polar reduced). Updates `eye` and `target` in place;
 * returns false when it did not move them (already high enough, or already at `minPolar`). When
 * `minY` is out of reach the steepest legal pose is taken.
 */
export function raiseRigAbout(eye: Vector3, target: Vector3, pivotIn: Vector3, minY: number, minPolar: number): boolean {
  if (eye.y >= minY) return false;
  const pivot = _pivot.copy(pivotIn);
  _off.copy(eye).sub(target);
  const horiz = Math.hypot(_off.x, _off.z);
  if (!(horiz > 1e-6)) return false;
  _axis.set(-_off.z / horiz, 0, _off.x / horiz); // normalize(cross(h, up)): lifts the eye for a positive angle
  const cosCap = Math.cos(minPolar);
  const eyeAt = (a: number, out: Vector3): Vector3 => out.copy(eye).sub(pivot).applyAxisAngle(_axis, a).add(pivot);
  const cosPolarAt = (a: number): number => {
    _rot.copy(_off).applyAxisAngle(_axis, a);
    return _rot.y / Math.max(1e-9, _rot.length());
  };
  if (cosPolarAt(0) >= cosCap - 1e-9) return false;
  // Largest legal angle: where the view's polar reaches minPolar (cos polar is increasing in a).
  let lo = 0;
  let hi = Math.PI / 2;
  for (let i = 0; i < 40; i += 1) {
    const m = (lo + hi) / 2;
    if (cosPolarAt(m) <= cosCap) lo = m;
    else hi = m;
  }
  const maxA = lo;
  let a = maxA;
  if (eyeAt(maxA, _eyeTry).y > minY) {
    // The smallest angle that reaches minY (the eye's height is increasing in a on [0, maxA]).
    lo = 0;
    hi = maxA;
    for (let i = 0; i < 40; i += 1) {
      const m = (lo + hi) / 2;
      if (eyeAt(m, _eyeTry).y >= minY) hi = m;
      else lo = m;
    }
    a = hi;
  }
  if (!(a > 1e-9)) return false;
  const newEye = eyeAt(a, _eyeTry);
  target.sub(pivot).applyAxisAngle(_axis, a).add(pivot);
  eye.copy(newEye);
  return true;
}

/** The distance at which a sphere of `radius` fills SUBJECT_FILL of a `fovDeg` vertical field. */
export function subjectFloorDistance(radius: number, fovDeg: number): number {
  return radius / (SUBJECT_FILL * Math.tan((fovDeg * DEG) / 2));
}

const _lid = new Vector3();
const _off = new Vector3();
const _axis = new Vector3();
const _rot = new Vector3();
const _eyeTry = new Vector3();
const _pivot = new Vector3();
