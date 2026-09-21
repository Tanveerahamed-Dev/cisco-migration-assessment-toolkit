/**
 * interaction.ts — hit testing and pointer plumbing.
 *
 * Two decisions here are the difference between an app that feels solid and one that feels broken:
 *
 *   Link pick volume. A 2 px cable is a 2 px target, and a 2 px target is unhittable. LineSegments2
 *   raycasts in screen space and accepts `raycaster.params.Line2.threshold` as extra width in
 *   pixels, so links get a generous corridor around them. Without it a user clicks a cable four
 *   times, hits nothing, and concludes cables are not clickable.
 *
 *   Pick proxies on a dedicated layer. Devices are hit-tested against plain boxes that the camera
 *   never renders, not against the detailed chassis. The chassis is merged and instanced across
 *   five material groups, so raycasting it would mean five intersect calls against port grids and
 *   vent slots to answer a question a box answers exactly. The layer — not `visible = false` — is
 *   what keeps the proxies out of the render, because an invisible object's raycast behaviour is
 *   an implementation detail and a layer is a contract.
 *
 * Hover work is deferred to the frame. A pointermove that raycasts synchronously puts geometry
 * work on the input handler, which is exactly what the INP budget in acceptance E3 forbids; moves
 * record a position, wake the loop, and the raycast happens at most once per frame.
 */
import { Raycaster, Vector2, type Camera, type Object3D, type PerspectiveCamera } from "three";
import type { PickResult } from "./contract";
import { PICK_LAYER } from "./layers";

/**
 * Layer reserved for hit-test proxies. The camera renders layer 0 only, so nothing here is drawn —
 * an invariant that `postprocessing` broke once by allocating a Selection onto this same layer, so
 * the number now lives in `layers.ts` with the rest of the namespace and a collision check.
 */
export { PICK_LAYER };

/** Extra pick width, in CSS pixels, added around a cable's rendered width. */
export const LINK_PICK_THRESHOLD_PX = 9;

export interface PickSources {
  /** InstancedMesh of device bounding boxes, on PICK_LAYER. instanceId indexes `deviceIds`. */
  deviceProxy: Object3D | null;
  deviceIds: readonly string[];
  /** The rendered cable batches; `faceIndex` from a hit indexes the batch's segment id array. */
  linkObjects: readonly { object: Object3D; segmentLinkIds: readonly string[] }[];
  /** Screen-space anchor for a hit, so the caller can place a DOM label without a second project. */
  project(kind: "device" | "link", id: string): { x: number; y: number } | null;
}

export interface InteractionCallbacks {
  onHover(result: PickResult | null): void;
  onPick(result: PickResult | null, modifier: boolean): void;
  /** Called when a pointer event created work the render loop must wake up to do. */
  onNeedsFrame(): void;
}

export interface Interaction {
  /** Hit-test a client-space point. Public because `FabricScene.pick` forwards straight to it. */
  pick(clientX: number, clientY: number): PickResult | null;
  /** Run at most one hover raycast per frame. Called from the render loop, never from an event. */
  flushHover(): void;
  setEnabled(enabled: boolean): void;
  dispose(): void;
}

/** Below this movement a pointerup is a click; above it, it was a camera drag. */
const CLICK_SLOP_PX = 4;
const CLICK_MAX_MS = 700;

export function createInteraction(
  canvas: HTMLCanvasElement,
  camera: PerspectiveCamera,
  sources: PickSources,
  cb: InteractionCallbacks,
): Interaction {
  const raycaster = new Raycaster();
  raycaster.layers.enable(PICK_LAYER);
  raycaster.params.Line2 = { threshold: LINK_PICK_THRESHOLD_PX };
  const ndc = new Vector2();

  let enabled = true;
  let hoverX = 0;
  let hoverY = 0;
  let hoverPending = false;
  let hoverInside = false;
  let lastHoverKey: string | null = null;
  let downX = 0;
  let downY = 0;
  let downAt = 0;
  let downValid = false;

  const toNdc = (clientX: number, clientY: number): boolean => {
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    return true;
  };

  const hitTest = (clientX: number, clientY: number): PickResult | null => {
    if (!toNdc(clientX, clientY)) return null;
    raycaster.setFromCamera(ndc, camera as Camera);

    let bestKind: "device" | "link" | null = null;
    let bestId: string | null = null;
    let bestScore = Infinity;

    const proxy = sources.deviceProxy;
    if (proxy !== null) {
      const hits = raycaster.intersectObject(proxy, false);
      for (const hit of hits) {
        const idx = hit.instanceId;
        if (idx === undefined) continue;
        const id = sources.deviceIds[idx];
        if (id === undefined) continue;
        // Devices are biased to win a near-tie: a chassis is the object the user means when a
        // cable happens to cross in front of it, and the reverse almost never holds.
        const score = hit.distance * 0.85;
        if (score < bestScore) {
          bestScore = score;
          bestKind = "device";
          bestId = id;
        }
        break; // intersections are sorted; the first is the nearest face of the nearest proxy
      }
    }

    for (const batch of sources.linkObjects) {
      const hits = raycaster.intersectObject(batch.object, false);
      for (const hit of hits) {
        const seg = hit.faceIndex;
        if (seg === undefined || seg === null) continue;
        const id = batch.segmentLinkIds[seg];
        if (id === undefined) continue;
        if (hit.distance < bestScore) {
          bestScore = hit.distance;
          bestKind = "link";
          bestId = id;
        }
        break;
      }
    }

    if (bestKind === null || bestId === null) return null;
    const screen = sources.project(bestKind, bestId);
    return {
      kind: bestKind,
      id: bestId,
      // A null projection means the anchor is off-screen or behind the camera. The hit is still
      // real; the caller simply has nowhere on screen to put a label for it.
      screen: screen ?? { x: 0, y: 0 },
    };
  };

  const onPointerMove = (e: PointerEvent): void => {
    if (!enabled) return;
    hoverX = e.clientX;
    hoverY = e.clientY;
    hoverInside = true;
    hoverPending = true;
    cb.onNeedsFrame();
  };

  const onPointerLeave = (): void => {
    hoverInside = false;
    hoverPending = false;
    if (lastHoverKey !== null) {
      lastHoverKey = null;
      canvas.style.cursor = "";
      cb.onHover(null);
    }
  };

  /* determinism: `e.timeStamp` is a clock the browser handed us. It is compared against the next
     pointer event's, and the only thing the comparison decides is whether a gesture was a click or
     a drag. No rendered value is derived from it, and it is never stored beyond the gesture. */
  const onPointerDown = (e: PointerEvent): void => {
    if (!enabled || e.button !== 0) return;
    downX = e.clientX;
    downY = e.clientY;
    downAt = e.timeStamp;
    downValid = true;
  };

  /* determinism: the other half of the same measurement — see `onPointerDown`. The elapsed time
     picks between "rotate the camera" and "choose this device"; neither branch renders it. */
  const onPointerUp = (e: PointerEvent): void => {
    if (!enabled || !downValid || e.button !== 0) return;
    downValid = false;
    const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
    // An orbit drag must never also select. OrbitControls owns the same pointer stream, so the
    // only thing separating "rotate the camera" from "choose this device" is this threshold.
    if (moved > CLICK_SLOP_PX || e.timeStamp - downAt > CLICK_MAX_MS) return;
    const result = hitTest(e.clientX, e.clientY);
    cb.onPick(result, e.shiftKey || e.metaKey || e.ctrlKey);
  };

  const onPointerCancel = (): void => {
    downValid = false;
  };

  canvas.addEventListener("pointermove", onPointerMove, { passive: true });
  canvas.addEventListener("pointerleave", onPointerLeave, { passive: true });
  canvas.addEventListener("pointerdown", onPointerDown, { passive: true });
  canvas.addEventListener("pointerup", onPointerUp, { passive: true });
  canvas.addEventListener("pointercancel", onPointerCancel, { passive: true });

  return {
    pick(clientX: number, clientY: number): PickResult | null {
      return hitTest(clientX, clientY);
    },

    flushHover(): void {
      if (!hoverPending || !hoverInside || !enabled) return;
      hoverPending = false;
      const result = hitTest(hoverX, hoverY);
      const key = result === null ? null : `${result.kind}:${result.id}`;
      if (key === lastHoverKey) return;
      lastHoverKey = key;
      canvas.style.cursor = result === null ? "" : "pointer";
      cb.onHover(result);
    },

    setEnabled(next: boolean): void {
      enabled = next;
      if (!next) onPointerLeave();
    },

    dispose(): void {
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerCancel);
      canvas.style.cursor = "";
    },
  };
}
