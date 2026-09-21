/**
 * camera.ts — a constrained orbit, an eased move, and a depth range that is re-fitted every frame.
 *
 * Three things here are deliberate and each has a failure mode attached:
 *
 *   Constraint. Azimuth is free, polar is clamped to [12, 78] degrees, dolly to a band around the
 *   current framing distance. An unconstrained orbit lets the user end up underneath the fabric or
 *   in a plan view, both of which destroy the tier reading that the whole layout exists to produce.
 *
 *   Near/far re-fitting. design-brief.md §4.1 fixes near at 1.2 for a ~140-unit scene. This scene
 *   spans ~330 units and layout.ts frames it from ~500 away, so a fixed near would either clip the
 *   fabric when the user dollies in or throw away the depth precision that SSAO reads from. The
 *   planes are therefore refitted to the scene's bounding sphere on every camera change — which is
 *   the same fix the brief argues for (tighten near, do not reach for logarithmicDepthBuffer) with
 *   the constant replaced by the measurement it was standing in for.
 *
 *   No drift. There is no idle rotation and no ambient float. A camera that moves on its own makes
 *   a screenshot non-reproducible, and acceptance F6 requires two runs to produce identical
 *   captures.
 */
import { PerspectiveCamera, Vector3 } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { CameraFraming } from "./contract";

const DEG = Math.PI / 180;
const MIN_POLAR = 12 * DEG;
const MAX_POLAR = 78 * DEG;
const DOLLY_IN = 0.55;
const DOLLY_OUT = 2.4;

/**
 * Padding around the fabric's bounding sphere at the overview pose. 1.06 fills the stage without
 * letting an edge node touch the frame; the layout's own 1.15 was computed against a declared 16:9
 * and, replayed into a narrower stage, reads as a small drawing on a large canvas.
 */
const HOME_MARGIN = 1.06;

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
  reducedMotion: boolean;
  width: number;
  height: number;
}

export interface CameraRig {
  camera: PerspectiveCamera;
  controls: OrbitControls;
  /** True while an eased move is in flight. */
  isTweening(): boolean;
  /** Ease (or jump, under reduced motion) to a pose. */
  moveTo(target: CameraTarget, opts?: { immediate?: boolean }): void;
  /** The pose `resetCamera()` returns to; replaced when the data changes. */
  setHomeFraming(
    framing: CameraFraming,
    sphere: { center: [number, number, number]; radius: number },
    box?: { min: [number, number, number]; max: [number, number, number] },
  ): void;
  home(opts?: { immediate?: boolean }): void;
  setViewport(width: number, height: number): void;
  setReducedMotion(reduced: boolean): void;
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
const _fromPos = new Vector3();
const _fromTarget = new Vector3();
const _toPos = new Vector3();
const _toTarget = new Vector3();
const _sphereCenter = new Vector3();
const _forward = new Vector3();
const _right = new Vector3();
const _up = new Vector3();
const _corner = new Vector3();
const WORLD_UP = new Vector3(0, 1, 0);

export function createCameraRig(
  canvas: HTMLCanvasElement,
  opts: CameraRigOptions,
): CameraRig {
  const fov = opts.framing.fovDeg ?? 45;
  const camera = new PerspectiveCamera(fov, opts.width / Math.max(1, opts.height), 1, 1000);
  camera.position.set(...opts.framing.position);

  const controls = new OrbitControls(camera, canvas);
  controls.target.set(...opts.framing.target);
  controls.enableDamping = true;
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
  let homeBox: { min: [number, number, number]; max: [number, number, number] } | null =
    opts.box ?? null;
  let reducedMotion = opts.reducedMotion;

  const homePose = (): CameraTarget => {
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

  const applyDollyBand = (): void => {
    const d = camera.position.distanceTo(controls.target);
    // The band follows the CURRENT framing, not the overview framing. Focusing on one device puts
    // the camera far inside the overview's inner limit; a fixed band would then either refuse to
    // zoom in at all or refuse to pull back out.
    controls.minDistance = Math.max(sphereRadius * 0.06, d * DOLLY_IN);
    controls.maxDistance = Math.max(d * DOLLY_OUT, sphereRadius * 4);
  };

  const refitDepth = (): void => {
    const d = camera.position.distanceTo(_sphereCenter);
    // Quantised, then applied unconditionally. A hysteresis band here ("only update past 1 %")
    // makes the projection depend on the PATH the camera took rather than on where it ended up:
    // two runs that reach the same pose through a different number of tween frames end with
    // different near/far and therefore different pixels. Quantising to a fixed grid keeps the
    // update cheap — the value only actually changes when the camera has moved a real distance —
    // while making it a pure function of the current pose, which is what F6 needs.
    const q = Math.max(0.5, sphereRadius * 0.002);
    const near = Math.max(1, Math.round((d - sphereRadius * 1.05) / q) * q);
    const far = Math.max(near + 10, Math.round((d + sphereRadius * 1.8) / q) * q);
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
      sphereRadius = Math.max(1, sphere.radius);
      _sphereCenter.set(...sphere.center);
      applyDollyBand();
      refitDepth();
    },

    home(homeOpts?: { immediate?: boolean }): void {
      rig.moveTo(homePose(), homeOpts);
    },

    setViewport(width: number, height: number): void {
      camera.aspect = width / Math.max(1, height);
      camera.updateProjectionMatrix();
      if (!userMoved && !tweenActive) {
        snapHome();
        applyDollyBand();
        refitDepth();
      }
    },

    setReducedMotion(reduced: boolean): void {
      reducedMotion = reduced;
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
      if (controls.update() || moved) {
        moved = true;
        refitDepth();
      }
      return moved;
    },

    dispose(): void {
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
  const vFov = camera.fov * DEG;
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const dist = (Math.max(radius, 1) * margin) / Math.sin(Math.min(vFov, hFov) / 2);
  return {
    position: [center.x + _v.x * dist, center.y + _v.y * dist, center.z + _v.z * dist],
    target: [center.x, center.y, center.z],
  };
}
