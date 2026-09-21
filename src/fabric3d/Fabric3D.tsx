/**
 * Fabric3D.tsx — the only place React and the three.js scene meet.
 *
 * The division of labour is the one `contract.ts` describes: React owns the DOM and the
 * investigation state, the scene owns the canvas, and this file translates between them with
 * imperative calls. Nothing here schedules React work per frame, and no pointer or key event is
 * routed through a reconciler before it reaches the scene — that is what keeps the INP budget and
 * the frame budget independent of each other.
 *
 * Three decisions in here are load-bearing and are explained where they are made:
 *   1. the canvas element is created imperatively, one per scene instance (StrictMode safety),
 *   2. store subscriptions are per-slice, so an evidence-pane change cannot re-render the stage,
 *   3. the keyboard contract is a first-class input path, not a fallback for the mouse.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { failureImpact, linkFailureImpact } from "../analysis/blast";
import { bandOfHop } from "../core/claims";
import { deviceById, fabric, findingsByHost, linkById, linksByHost } from "../core/data";
import { applyToDevices, parseQuery } from "../core/query";
import { useInvestigation, useReducedMotion } from "../core/store";
import type { Device, Link, Trace } from "../core/types";

import type { FabricScene, HighlightState, PickResult, QualityTier, SceneEvent } from "./contract";
import { FabricA11yTree } from "./FabricA11yTree";
import { createHoverChannel, FabricLabels, type HoverChannel } from "./FabricLabels";
import { publishSceneStats, releaseSceneStats } from "./telemetry";
import { FabricLegend } from "./FabricLegend";
import { computeLayout } from "./layout";
import { exposeSceneForCapture } from "./devHandle";
import { createScene, type FabricSceneEx } from "./scene";

import "./Fabric3D.css";

/** Pointer travel (CSS px) above which a press is an orbit drag, not a click on a node. */
const DRAG_SLOP = 4;

/** One wheel notch. The contract exposes no dolly verb, so keyboard zoom speaks the scene's
 *  own input language rather than inventing a camera API the scene does not implement. */
const KEY_ZOOM_DELTA = 120;

/** Half-angle of the cone an arrow key searches, as a cosine. 60° keeps a diagonal neighbour
 *  reachable while refusing to call a node "to the right" when it is mostly above. */
const DIRECTION_COS_LIMIT = 0.5;

const DIRECTIONS: Readonly<Record<string, readonly [number, number]>> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  /** Screen Y grows downward, so "up" is negative. */
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/**
 * THE FABRIC HAS THREE ENDINGS FOR A TRACE, NOT TWO, AND IT DOES NOT DECIDE THEM HERE.
 *
 * It used to hold a hand-written set of "failing verdicts" with `unmodeled` folded in beside
 * `denied`. The intent was right — a hop the engine could not model is not a hop that succeeded —
 * but the rendering was not: an indeterminate hop was drawn with the denied treatment and the word
 * BLOCKED, byte-for-byte identical to a genuinely denied flow, while the side panel for the very
 * same trace said INDETERMINATE. The surface asserted a definite failure the engine had explicitly
 * refused to assert, which is the mirror image of the absence-as-health defect this product exists
 * to refuse: absence rendered as a FAULT is still absence rendered as a measurement.
 *
 * The root cause was not the missing third case; it was that this file restated the
 * verdict → disposition mapping at all. `claims.ts :: bandOfHop` is the one owner of that mapping
 * (REFUTED / UNDETERMINED / RESOLVED) and every other surface — HopList's badge, the claim badge,
 * the Inspector's treatment — already asks it. So the fabric asks it too, and a new verdict added
 * to `HopVerdict` can no longer land in this file's set by default.
 */
export type TraceMarkKind =
  /** REFUTED: the traced packet was stopped here, and the engine says by what. */
  | "blocked"
  /** UNDETERMINED: the simulation ran and declined to decide. Not a stop, not a delivery. */
  | "undetermined"
  /** RESOLVED: the traced packet reached its destination at this hop. */
  | "delivered";

interface TraceMark {
  host: string;
  /** The cable the stopped packet would have taken. Only ever resolved for a REFUTED hop. */
  link: string | null;
  kind: TraceMarkKind;
}

export interface Fabric3DProps {
  devices?: Device[];
  links?: Link[];
  tiers?: readonly (readonly string[])[];
  className?: string;
  /** Pin the render quality instead of letting the scene probe for one. */
  quality?: QualityTier;
}

/* ── theme, read live from the document so an explicit choice beats the OS ──── */

const readTheme = (): "dark" | "light" => {
  if (typeof document === "undefined") return "dark";
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "dark" || explicit === "light") return explicit;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
};

function useTheme(): "dark" | "light" {
  const subscribe = useCallback((onChange: () => void) => {
    const mq = typeof window !== "undefined" ? window.matchMedia?.("(prefers-color-scheme: dark)") : null;
    mq?.addEventListener("change", onChange);
    const obs =
      typeof MutationObserver !== "undefined"
        ? new MutationObserver(onChange)
        : null;
    obs?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq?.removeEventListener("change", onChange);
      obs?.disconnect();
    };
  }, []);
  return useSyncExternalStore(subscribe, readTheme, () => "dark");
}

/* ── keyboard traversal over projected screen positions ────────────────────── */

interface Projected {
  id: string;
  x: number;
  y: number;
}

function projectAll(scene: FabricScene, devices: readonly Device[]): Projected[] {
  const out: Projected[] = [];
  for (const d of devices) {
    const p = scene.project(d.id);
    if (p && p.visible) out.push({ id: d.id, x: p.x, y: p.y });
  }
  return out;
}

/**
 * The device nearest the centre of what is currently on screen. The centre is the centroid of the
 * projected nodes rather than the canvas midpoint, because `project()`'s coordinate space is the
 * scene's business and this must not assume it is canvas-local.
 */
function nearestToCentre(nodes: readonly Projected[]): string | null {
  if (nodes.length === 0) return null;
  let cx = 0;
  let cy = 0;
  for (const n of nodes) {
    cx += n.x;
    cy += n.y;
  }
  cx /= nodes.length;
  cy /= nodes.length;
  let best: Projected | null = null;
  let bestD = Infinity;
  for (const n of nodes) {
    const d = Math.hypot(n.x - cx, n.y - cy);
    // Ties break on id so two runs of the same capture select the same node (acceptance F6).
    if (d < bestD || (d === bestD && best !== null && n.id < best.id)) {
      best = n;
      bestD = d;
    }
  }
  return best ? best.id : null;
}

function nextInDirection(
  nodes: readonly Projected[],
  from: Projected,
  dir: readonly [number, number],
): string | null {
  let best: Projected | null = null;
  let bestScore = Infinity;
  for (const n of nodes) {
    if (n.id === from.id) continue;
    const vx = n.x - from.x;
    const vy = n.y - from.y;
    const dist = Math.hypot(vx, vy);
    if (dist < 1) continue;
    const along = vx * dir[0] + vy * dir[1];
    if (along <= 0) continue;
    const cos = along / dist;
    if (cos < DIRECTION_COS_LIMIT) continue;
    // Distance penalised by how far off-axis the candidate sits, so a node straight ahead beats a
    // slightly nearer one at the edge of the cone.
    const score = dist / cos;
    if (score < bestScore || (score === bestScore && best !== null && n.id < best.id)) {
      best = n;
      bestScore = score;
    }
  }
  return best ? best.id : null;
}

/** Fallback traversal for the window before the first frame, when nothing projects yet. Clamped
 *  rather than wrapping: a keyboard user in a spatial view should not teleport across the fabric. */
function stepByOrder(devices: readonly Device[], current: string | null, delta: 1 | -1): string | null {
  if (devices.length === 0) return null;
  const at = current === null ? -1 : devices.findIndex((d) => d.id === current);
  if (at < 0) return devices[delta === 1 ? 0 : devices.length - 1]?.id ?? null;
  const next = Math.min(devices.length - 1, Math.max(0, at + delta));
  return devices[next]?.id ?? null;
}

/* ── announcements: a canvas selection is invisible to assistive technology ── */

export function describeDevice(id: string): string {
  const d = deviceById.get(id);
  if (!d) return `Device ${id} selected. No device record in this snapshot.`;
  const degree = linksByHost.get(d.host)?.length ?? linksByHost.get(d.id)?.length ?? 0;
  /* A finding tally for a device nobody assessed is a zero produced by never having looked, and
     this announcement is the ONLY channel a screen-reader user has here — there is no visible
     panel beside it to carry the qualification. DevicePane already refuses to state this number
     for an uncollected device ("finding counts: not observed ... a severity tally here would
     count an empty search rather than an assessed device"); two surfaces of one product must not
     disagree about whether a number may be stated at all. `?? 0` is kept only on the collected
     branch, where the zero is a real measurement. */
  const findingClause = d.collected
    ? (() => {
        const n = findingsByHost.get(d.host)?.length ?? 0;
        return `${n} ${n === 1 ? "finding" : "findings"}.`;
      })()
    : "Finding count not observed — this device was never collected, so a tally would count an empty search rather than an assessed device.";
  return [
    `${d.host} selected.`,
    `${d.kind}.`,
    d.collected ? "Collected." : "Topology only: this device was never collected.",
    `Health band ${d.band ?? "not observed"}.`,
    `Role ${d.role ?? "not observed"}.`,
    `Tier ${d.tier === null ? "not observed" : d.tier}.`,
    `Operational state ${d.opStatus}.`,
    `${degree} ${degree === 1 ? "link" : "links"}.`,
    findingClause,
  ].join(" ");
}

function describeLink(id: string): string {
  const l = linkById.get(id);
  if (!l) return `Link ${id} selected. No link record in this snapshot.`;
  return [
    `Link ${l.id} selected.`,
    `${l.a} ${l.aPort ?? "port not observed"} to ${l.b} ${l.bPort ?? "port not observed"}.`,
    `Operational state ${l.opStatus}.`,
    l.speedMbps === null ? "Speed not observed." : `${l.speedMbps} megabit per second.`,
    l.isBridge === null
      ? "Centrality was not computed for this link, so whether cutting it partitions the fabric is unknown."
      : l.isBridge
        ? "Cutting this link partitions the fabric."
        : "A redundant path exists around this link.",
  ].join(" ");
}

/* ── highlight derivation ──────────────────────────────────────────────────── */

interface Blocked {
  host: string | null;
  link: string | null;
}

/** Reference-stable "no blast radius", so an unrelated re-render cannot invalidate the memo. */
const NO_BLAST: { stranded: readonly string[]; host: string | null; link: string | null } = {
  stranded: [],
  host: null,
  link: null,
};
const EMPTY_SET: ReadonlySet<string> = new Set<string>();

const NO_BLOCK: Blocked = { host: null, link: null };

/**
 * Where the traced packet's story ends on the fabric, and WHICH of the three endings it is.
 *
 * The first hop the claim layer does not call RESOLVED is where the story ends: a packet stops at
 * the first REFUTED hop and stops being decidable at the first UNDETERMINED one, so hop order —
 * not verdict severity — picks the mark. A trace every hop of which resolved is marked at its last
 * hop, and only when that hop actually says `delivered`: a run of `forwarded` hops that simply ran
 * out is not a delivery, and marking it as one would be this defect with the sign flipped.
 */
function traceMarkOf(trace: Trace | null): TraceMark | null {
  if (!trace || trace.hops.length === 0) return null;
  const stop = trace.hops.find((h) => bandOfHop(h) !== "RESOLVED");
  if (stop === undefined) {
    const last = trace.hops[trace.hops.length - 1];
    return last !== undefined && last.verdict === "delivered"
      ? { host: last.host, link: null, kind: "delivered" }
      : null;
  }
  const kind: TraceMarkKind = bandOfHop(stop) === "REFUTED" ? "blocked" : "undetermined";
  /* The cable is resolved for the REFUTED case alone. It feeds the scene's alarm channel, and
     alarming the cable out of a hop the engine could not decide would restate the same overclaim
     one object further along. */
  let link: string | null = null;
  if (kind === "blocked" && stop.nextHost !== null) {
    const candidates = linksByHost.get(stop.host) ?? [];
    const match = candidates.find((l) => l.a === stop.nextHost || l.b === stop.nextHost);
    link = match ? match.id : null;
  }
  return { host: stop.host, link, kind };
}

/**
 * The scene's alarm channel, which is the CANVAS treatment (a red outline on the chassis).
 *
 * Only a REFUTED hop earns it. `blockedHost` is how a reader tells a stopped flow from one that
 * was not stopped, and the contract's own word for it is "the failing element" — an undecided hop
 * is not a failing element, and a delivered one certainly is not. The other two endings are
 * carried by the label layer's own marks, which say in words which of the three this is.
 */
const blockedOf = (mark: TraceMark | null): Blocked =>
  mark !== null && mark.kind === "blocked" ? { host: mark.host, link: mark.link } : NO_BLOCK;

/* ── component ─────────────────────────────────────────────────────────────── */

export function Fabric3D({
  devices = fabric.devices,
  links = fabric.links,
  tiers = fabric.tiers,
  className,
  quality,
}: Fabric3DProps = {}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasSlotRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  /* `FabricSceneEx`, not `FabricScene`: the diagnostics the HUD reports (a standing draw-call
     breach among them) are declared on the widened handle scene.ts returns. Typed as the frozen
     contract, `overBudget` would be reachable only through a cast, which is how it stayed
     invisible while the product breached its ceiling on every traced frame. */
  const sceneRef = useRef<FabricSceneEx | null>(null);

  const helpId = useId();
  const legendId = useId();
  /** Describes the Fabric-list toggle: see the note beside that button. */
  const treeNoteId = useId();

  /* Narrow slices only. A change to the evidence tab, the palette or the finding list must not
     re-render the stage at all, let alone touch the scene. */
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const findingId = useInvestigation((s) => s.findingId);
  const trace = useInvestigation((s) => s.trace);
  const hopIndex = useInvestigation((s) => s.hopIndex);
  const query = useInvestigation((s) => s.query);
  const severities = useInvestigation((s) => s.severities);
  const roles = useInvestigation((s) => s.roles);
  const onlyUncollected = useInvestigation((s) => s.onlyUncollected);

  const theme = useTheme();
  const reducedMotion = useReducedMotion();

  const hover = useMemo<HoverChannel>(() => createHoverChannel(), []);
  const layout = useMemo(() => computeLayout({ devices, links, tiers }), [devices, links, tiers]);

  const [sceneEpoch, setSceneEpoch] = useState(0);
  const [qualityTier, setQualityTier] = useState<QualityTier | null>(quality ?? null);
  const [treeVisible, setTreeVisible] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [sceneError, setSceneError] = useState<string | null>(null);
  /**
   * A STANDING draw-call breach, with the numbers that make it checkable.
   *
   * `null` is "no standing breach", which is the normal state. This is React state rather than a
   * dev-only console line because acceptance E4 says degradation is explicit and never silent, and
   * a `console.error` guarded by `import.meta.env.DEV` is absent from every shipped chunk — so the
   * only report of a live breach was one nobody running the product could ever see.
   */
  const [breach, setBreach] = useState<{ calls: number; budget: number; outlines: number } | null>(null);

  /* Latest values the construction path needs, so the create effect can depend on almost nothing
     and still build the scene from current data. */
  const optsRef = useRef({ devices, links, layout, theme, quality });
  optsRef.current = { devices, links, layout, theme, quality };
  const devicesRef = useRef(devices);
  devicesRef.current = devices;

  const onEvent = useCallback((e: SceneEvent) => {
    switch (e.type) {
      case "pick":
        applyPick(e.result);
        break;
      case "hover":
        hover.set(
          e.result === null
            ? { deviceId: null, linkId: null }
            : e.result.kind === "device"
              ? { deviceId: e.result.id, linkId: null }
              : { deviceId: null, linkId: e.result.id },
        );
        break;
      case "stats": {
        // Only the tier and a STANDING budget breach are surfaced, and only when they change: fps
        // is a per-frame value and rendering it would put React back on the frame path it was kept
        // off. The stats event fires at most twice a second, so this costs nothing per frame.
        setQualityTier((prev) => (prev === e.stats.quality ? prev : e.stats.quality));
        /* Read the WIDENED stats off the handle. `SceneEvent` is declared in the frozen contract
           and its payload is typed `SceneStats`, which does not name `overBudget`; the handle
           does. Reading it here rather than casting `e.stats` is what keeps this type-checked. */
        const ex = sceneRef.current?.stats();
        /* The whole reading, to the one channel the status bar subscribes to. Before this, every
           field except the tier died here and the bar said the subsystem had never reported a
           frame while it was reporting one twice a second. */
        publishSceneStats(ex ?? null);
        setBreach((prev) => {
          const next =
            ex === undefined || !ex.overBudget
              ? null
              : { calls: ex.drawCalls, budget: ex.drawCallBudget, outlines: ex.activeOutlines };
          if (prev === next) return prev;
          if (prev !== null && next !== null && prev.calls === next.calls && prev.budget === next.budget) {
            return prev;
          }
          return next;
        });
        break;
      }
      case "camera":
        break;
    }
  }, [hover]);

  /*
   * Scene lifetime. The canvas element is created here rather than rendered by React because a
   * disposed WebGL context cannot be re-acquired on the same canvas element: under StrictMode's
   * mount/unmount/mount the second scene would come up black on a React-owned canvas, and the
   * failure is silent. One canvas per scene instance makes the double-invoke safe by construction,
   * and removing it on cleanup is what proves no context leaked.
   *
   * `reducedMotion` is a dependency because the contract exposes no setter for it and a stale
   * motion preference is an accessibility defect; the lost camera pose on that rare OS change is
   * the cheaper of the two costs.
   */
  useEffect(() => {
    const slot = canvasSlotRef.current;
    if (!slot) return;

    const canvas = slot.ownerDocument.createElement("canvas");
    canvas.className = "fabric3d__canvas";
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "application");
    canvas.setAttribute("aria-label", "Network fabric, three-dimensional view");
    canvas.setAttribute("aria-describedby", helpId);
    canvas.setAttribute(
      "aria-keyshortcuts",
      "ArrowUp ArrowDown ArrowLeft ArrowRight Enter Escape Home Plus Minus",
    );
    canvas.dataset.testid = "fabric3d-canvas";
    canvas.dataset.hovering = "false";
    slot.appendChild(canvas);
    canvasRef.current = canvas;

    const o = optsRef.current;
    let scene: FabricSceneEx;
    try {
      scene = createScene(
        canvas,
        {
          devices: o.devices,
          links: o.links,
          layout: o.layout,
          theme: o.theme,
          reducedMotion,
          ...(o.quality ? { quality: o.quality } : {}),
        },
        { onEvent },
      );
    } catch (err) {
      // No WebGL, a lost context, or a driver that refuses the request. The fabric is still fully
      // available through the tree, and saying so is the honest answer; throwing here would take
      // the whole investigation down with the renderer.
      canvas.remove();
      canvasRef.current = null;
      setSceneError(err instanceof Error ? err.message : String(err));
      return;
    }
    setSceneError(null);
    sceneRef.current = scene;

    /* Publish the handle for the review harnesses (dev/test builds only; a no-op in production).
       `review/capture.mjs` waits on `stats().converged` before screenshotting, so a frame is taken
       at a DEFINED moment rather than after a fixed sleep — a sleep produces a different frame on a
       different machine and silently breaks the byte-identical-capture requirement (acceptance F6).
       `review/measure-inp.mjs` and `review/probe-fabric.mjs` read it too. */
    const releaseHandle = exposeSceneForCapture(scene);

    /* ── input, attached directly to the canvas ── */

    const press = { down: false, moved: false, x: 0, y: 0 };
    let hoverFrame = 0;
    let hoverAt: { x: number; y: number } | null = null;

    const pickAt = (x: number, y: number): PickResult | null => scene.pick(x, y);

    const runHover = () => {
      hoverFrame = 0;
      if (!hoverAt) return;
      const r = pickAt(hoverAt.x, hoverAt.y);
      hover.set(
        r === null
          ? { deviceId: null, linkId: null }
          : r.kind === "device"
            ? { deviceId: r.id, linkId: null }
            : { deviceId: null, linkId: r.id },
      );
      scene.setHover(r && r.kind === "device" ? r.id : null, r && r.kind === "link" ? r.id : null);
      canvas.dataset.hovering = r === null ? "false" : "true";
    };

    const onPointerDown = (e: PointerEvent) => {
      press.down = true;
      press.moved = false;
      press.x = e.clientX;
      press.y = e.clientY;
      // A canvas does not take focus from a press in every browser, and the keyboard contract is
      // useless if a click leaves focus behind on whatever was focused before.
      canvas.focus({ preventScroll: true });
    };

    const onPointerMove = (e: PointerEvent) => {
      if (press.down) {
        if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > DRAG_SLOP) press.moved = true;
        return; // hover during an orbit drag is noise
      }
      hoverAt = { x: e.clientX, y: e.clientY };
      // Coalesce to one hit-test per frame: pointermove fires far faster than the scene redraws.
      if (hoverFrame === 0) hoverFrame = requestAnimationFrame(runHover);
    };

    const endPress = () => {
      press.down = false;
      press.moved = false;
    };

    const onPointerUp = (e: PointerEvent) => {
      const wasClick = press.down && !press.moved;
      endPress();
      if (!wasClick) return;
      applyPick(pickAt(e.clientX, e.clientY));
    };

    const onPointerLeave = () => {
      endPress();
      hoverAt = null;
      if (hoverFrame !== 0) {
        cancelAnimationFrame(hoverFrame);
        hoverFrame = 0;
      }
      hover.set({ deviceId: null, linkId: null });
      scene.setHover(null, null);
      canvas.dataset.hovering = "false";
    };

    const onDoubleClick = (e: MouseEvent) => {
      const r = pickAt(e.clientX, e.clientY);
      if (r && r.kind === "device") {
        useInvestigation.getState().selectDevice(r.id, { surface: "fabric" });
        scene.focusDevice(r.id);
      }
    };

    const zoom = (direction: 1 | -1) => {
      if (typeof WheelEvent === "undefined") return;
      const rect = canvas.getBoundingClientRect();
      canvas.dispatchEvent(
        new WheelEvent("wheel", {
          deltaY: direction * KEY_ZOOM_DELTA,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2,
          bubbles: true,
          cancelable: true,
        }),
      );
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const st = useInvestigation.getState();
      const dir = DIRECTIONS[e.key];
      if (dir) {
        e.preventDefault();
        const nodes = projectAll(scene, devicesRef.current);
        const current = st.deviceId;
        let next: string | null;
        if (nodes.length === 0) {
          next = stepByOrder(devicesRef.current, current, dir[0] + dir[1] > 0 ? 1 : -1);
        } else {
          const from = current === null ? null : (nodes.find((n) => n.id === current) ?? null);
          next = from === null ? nearestToCentre(nodes) : nextInDirection(nodes, from, dir);
        }
        if (next !== null) st.selectDevice(next, { surface: "fabric" });
        return;
      }
      switch (e.key) {
        case "Enter":
          e.preventDefault();
          if (st.deviceId !== null) scene.focusDevice(st.deviceId);
          break;
        case "Escape":
          // Only swallow Escape when there is a selection to clear, so an overlay above the stage
          // still receives it.
          if (st.deviceId !== null || st.linkId !== null) {
            e.preventDefault();
            st.selectDevice(null);
            st.selectLink(null);
          }
          break;
        case "Home":
          e.preventDefault();
          scene.resetCamera();
          break;
        case "+":
        case "=":
          e.preventDefault();
          zoom(-1);
          break;
        case "-":
        case "_":
          e.preventDefault();
          zoom(1);
          break;
        default:
          break;
      }
    };

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerLeave);
    canvas.addEventListener("pointerleave", onPointerLeave);
    canvas.addEventListener("dblclick", onDoubleClick);
    canvas.addEventListener("keydown", onKeyDown);

    setSceneEpoch((n) => n + 1);

    return () => {
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerLeave);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("dblclick", onDoubleClick);
      canvas.removeEventListener("keydown", onKeyDown);
      if (hoverFrame !== 0) cancelAnimationFrame(hoverFrame);
      releaseHandle();
      /* "Not observed" has to mean it: a released scene must not leave its last reading on screen
         as though it were live. */
      releaseSceneStats();
      sceneRef.current = null;
      canvasRef.current = null;
      scene.dispose();
      canvas.remove();
    };
  }, [onEvent, hover, helpId, reducedMotion]);

  /* ── data: replaced imperatively, never by rebuilding the scene ──────────── */

  const appliedRef = useRef<{
    scene: FabricScene | null;
    devices: Device[] | null;
    links: Link[] | null;
    layout: unknown;
  }>({ scene: null, devices: null, links: null, layout: null });

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const prev = appliedRef.current;
    // A scene that was just constructed already holds this data; calling setData on it would throw
    // away GPU resources the contract asks to reuse.
    const isFresh = prev.scene !== scene;
    if (!isFresh && (prev.devices !== devices || prev.links !== links || prev.layout !== layout)) {
      scene.setData(devices, links, layout);
    }
    appliedRef.current = { scene, devices, links, layout };
  }, [sceneEpoch, devices, links, layout]);

  useEffect(() => {
    sceneRef.current?.setSelection(deviceId, linkId);
  }, [sceneEpoch, deviceId, linkId]);

  useEffect(() => {
    sceneRef.current?.setTrace(trace, hopIndex);
  }, [sceneEpoch, trace, hopIndex]);

  useEffect(() => {
    sceneRef.current?.setTheme(theme);
  }, [sceneEpoch, theme]);

  useEffect(() => {
    if (quality) sceneRef.current?.setQuality(quality);
  }, [sceneEpoch, quality]);

  /* ── blast radius, on the fabric ─────────────────────────────────────────────
   *
   * A6 asks that selecting a device or a link show what becomes unreachable. It was shown — in the
   * Inspector, as a list — and drawn nowhere. `HighlightState` was built from the query, the
   * severity and role filters and the selected finding, and from nothing else: selecting core1,
   * which this application itself says strands nine hosts, marked core1's label and left the nine
   * rendered exactly like every other node. Measured before this existed: core1 (9 stranded) vs
   * dist1 (no partition) differed by 1.29 % of the canvas, and two no-partition selections
   * differed from each other by 0.61 % — i.e. the partition case was indistinguishable from noise.
   *
   * It goes through `blockedHost` / `blockedLink` deliberately: the contract names that pair "the
   * failing element in a trace OR BLAST ANALYSIS, drawn with the alarm treatment", so this is the
   * channel it was designed for, not a filter-emphasis channel borrowed for a second purpose. The
   * stranded hosts join the emphasis set so they lift out of the dimmed field, and their labels
   * carry a `stranded` mark of their own (FabricLabels) so the class is legible without colour and
   * cannot be confused with a filter match.
   *
   * The same `failureImpact` / `linkFailureImpact` the Inspector reads, so the two surfaces cannot
   * tell different stories about one graph.
   */
  const blast = useMemo((): { stranded: readonly string[]; host: string | null; link: string | null } => {
    if (linkId !== null) {
      const r = linkFailureImpact(linkId);
      return r.newlyStranded.length === 0
        ? NO_BLAST
        : { stranded: r.newlyStranded, host: null, link: linkId };
    }
    if (deviceId !== null) {
      const host = deviceById.get(deviceId)?.host ?? deviceId;
      const r = failureImpact(host);
      return r.newlyStranded.length === 0 ? NO_BLAST : { stranded: r.newlyStranded, host, link: null };
    }
    return NO_BLAST;
  }, [deviceId, linkId]);

  /** Stranded host NAMES resolved to device ids, which is what the highlight set is keyed on. */
  const strandedIds = useMemo((): ReadonlySet<string> => {
    if (blast.stranded.length === 0) return EMPTY_SET;
    const want = new Set(blast.stranded);
    const out = new Set<string>();
    for (const d of devices) if (want.has(d.host) || want.has(d.id)) out.add(d.id);
    return out;
  }, [blast, devices]);

  /** The traced packet's ending, decided once and shared by the canvas channel and the label layer
   *  so the two cannot tell different stories about one trace. */
  const traceMark = useMemo(() => traceMarkOf(trace), [trace]);

  const highlight = useMemo<HighlightState | null>(() => {
    /* The scene's alarm halo stays TRACE-ONLY, deliberately, even though the contract would let a
       blast analysis fill the same field. The halo is how a reader tells a denied flow from a
       delivered one, and the cut points of this fabric include the very hosts most traces pass
       through: routing the blast radius through it made a delivered trace and a denied one differ
       by the label alone again — the same defect, moved. A cut point is a hypothesis, a blocked
       hop is a fact about the packet in front of you; they get different channels. The blast
       radius is drawn by the stranded emphasis set and by the label marks below. */
    const blocked = blockedOf(traceMark);
    const filtered =
      query.trim().length > 0 || severities.size > 0 || roles.size > 0 || onlyUncollected;
    /* A4: a selected finding must re-aim the fabric, because the fabric is the surface that answers
       "where in the network is this?". Before this, findingId was not an input to this memo at all,
       so selecting a finding produced a BYTE-IDENTICAL canvas — the fabric could not locate a
       finding, which is the one thing it is there for.
       Emphasis only: the finding's hosts join the highlight set and everything else recedes. The
       camera is deliberately untouched — re-aiming is not a flight, and moving the camera on every
       queue click would lose the pose the reader is working in. */
    const finding =
      findingId === null ? null : (fabric.findings.find((f) => f.id === findingId) ?? null);
    if (!filtered && finding === null && strandedIds.size === 0) {
      return blocked.host === null && blocked.link === null
        ? null
        : { hosts: [], links: [], blockedHost: blocked.host, blockedLink: blocked.link };
    }

    /* The filter contributes matches only when a filter is actually set. With no filter and a
       finding selected, the emphasis set is the finding's devices alone. */
    let matched: Device[] = filtered ? applyToDevices(devices, parseQuery(query)).items : [];
    // A device whose role was never observed is not "not in the access role"; it is unknown. It
    // falls out of a role filter the same way, but it is dimmed rather than hidden, so the viewer
    // can still see that the fabric holds devices the filter could not decide about.
    if (roles.size > 0) matched = matched.filter((d) => d.role !== null && roles.has(d.role));
    if (onlyUncollected) matched = matched.filter((d) => !d.collected);
    if (severities.size > 0) {
      const hosts = new Set<string>();
      for (const f of fabric.findings) {
        if (!severities.has(f.severity)) continue;
        for (const h of f.devices) hosts.add(h);
      }
      matched = matched.filter((d) => hosts.has(d.host) || hosts.has(d.id));
    }

    const hostIds = new Set(matched.map((d) => d.id));
    const hostNames = new Set(matched.map((d) => d.host));
    /* The selected finding's devices are UNIONED in rather than intersected: the reader chose this
       finding explicitly, so it must be findable on the fabric even when an unrelated filter is
       also set. Both are emphasis, and emphasis dims rather than hides, so a union cannot conceal
       anything the filter was meant to reveal. Matched by host or id, the same way the severity
       filter above resolves `finding.devices`. */
    if (finding !== null) {
      const named = new Set(finding.devices);
      for (const d of devices) {
        if (named.has(d.host) || named.has(d.id)) {
          hostIds.add(d.id);
          hostNames.add(d.host);
        }
      }
    }
    /* The stranded set joins the same way, and for the same reason: what becomes unreachable is
       what the reader asked about, so it must lift out of the dimmed field even when an unrelated
       filter is set. The label layer distinguishes it from a filter match. */
    for (const id of strandedIds) {
      hostIds.add(id);
      const d = deviceById.get(id);
      if (d) hostNames.add(d.host);
    }
    const linkIds = links
      .filter((l) => (hostIds.has(l.a) || hostNames.has(l.a)) && (hostIds.has(l.b) || hostNames.has(l.b)))
      .map((l) => l.id);
    return {
      hosts: [...hostIds],
      links: linkIds,
      blockedHost: blocked.host,
      blockedLink: blocked.link,
    };
  }, [devices, links, query, severities, roles, onlyUncollected, traceMark, findingId, blast, strandedIds]);

  /* TWO CLAIMS, TWO CHANNELS — they are no longer allowed to displace each other.
     "This hop ended the traced packet's story, and how" is a FACT about the packet in front of the
     reader. "Removing this host would cut other hosts off the fabric" is a HYPOTHESIS about a
     failure that has not happened. They were competing for one `data-alarm` slot, which meant the
     winner silently erased the loser: a delivered flow over an articulation point could say only
     one of the two true things about that host. Each gets its own attribute on the label now, so
     neither statement can overwrite the other — the same reason `selected` and `stranded` are
     already separate channels. */
  const labelAlarm = useMemo((): { id: string; kind: TraceMarkKind } | null =>
    traceMark === null ? null : { id: traceMark.host, kind: traceMark.kind },
  [traceMark]);

  const cutPointId = blast.host;

  useEffect(() => {
    sceneRef.current?.setHighlight(highlight);
  }, [sceneEpoch, highlight]);

  /* ── resize: one choke point, coalesced to a frame ───────────────────────── */

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let frame = 0;
    let pending: { w: number; h: number } | null = null;

    const flush = () => {
      frame = 0;
      if (pending) sceneRef.current?.resize(pending.w, pending.h);
    };
    const push = (w: number, h: number) => {
      // A zero-sized canvas is a division by zero in the projection matrix; clamp rather than
      // forwarding a collapsed layout to the renderer.
      pending = { w: Math.max(1, Math.round(w)), h: Math.max(1, Math.round(h)) };
      if (frame === 0) frame = requestAnimationFrame(flush);
    };

    const rect = host.getBoundingClientRect();
    push(rect.width, rect.height);

    // The cleanup is returned on every path, including the one where ResizeObserver is absent:
    // the initial push above has already armed a frame, and an unreturned cleanup leaks it.
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        for (const entry of entries) push(entry.contentRect.width, entry.contentRect.height);
      });
      ro.observe(host);
    }
    return () => {
      ro?.disconnect();
      if (frame !== 0) cancelAnimationFrame(frame);
    };
  }, [sceneEpoch]);

  /* ── announcements ───────────────────────────────────────────────────────── */

  const hadSelection = useRef(false);
  useEffect(() => {
    if (linkId !== null) {
      hadSelection.current = true;
      setAnnouncement(describeLink(linkId));
    } else if (deviceId !== null) {
      hadSelection.current = true;
      setAnnouncement(describeDevice(deviceId));
    } else if (hadSelection.current) {
      setAnnouncement("Fabric selection cleared.");
    }
  }, [deviceId, linkId]);

  const resetView = useCallback(() => {
    sceneRef.current?.resetCamera();
    canvasRef.current?.focus({ preventScroll: true });
  }, []);

  const focusDevice = useCallback((id: string) => {
    sceneRef.current?.focusDevice(id);
  }, []);

  const tierLabel = qualityTier ?? "probing";
  /* A reduced tier and a standing budget breach are both "this frame is not what the design
     specifies", and the chip marks either. They are worded apart so the reader is never left
     guessing which one happened. */
  const degraded = (qualityTier !== null && qualityTier !== "high") || breach !== null;
  const qualityTitle =
    breach !== null
      ? `Over the draw-call budget: this frame costs ${breach.calls} calls against a ceiling of ` +
        `${breach.budget} for a frame with ${breach.outlines} outline effect(s) active. ` +
        `It has been over for at least two consecutive rendered frames, so it is a standing cost, ` +
        `not a one-off rebuild.` +
        (qualityTier === null ? "" : ` Render quality tier in force: ${qualityTier}.`)
      : qualityTier === null
        ? "The scene has not yet reported a render quality tier."
        : `Render quality tier in force: ${qualityTier}. Draw calls are within the frame's budget.`;

  return (
    <div className={className === undefined ? "fabric3d" : `fabric3d ${className}`} ref={hostRef}>
      {/* React never puts children in this slot, so the imperatively-owned canvas cannot collide
          with reconciliation. */}
      <div className="fabric3d__canvas-host" ref={canvasSlotRef} />

      {/* scene.project() reports canvas-relative CSS pixels and this overlay is positioned against
          the canvas box, so the label loop must not subtract the container origin a second time. */}
      <FabricLabels
        devices={devices}
        sceneRef={sceneRef}
        epoch={sceneEpoch}
        hover={hover}
        selectedId={deviceId}
        /* The alarm treatment is drawn at the node ANCHOR, and the label box sits on that same
           anchor: measured, the halo survived only as thin slivers above and below the `core1`
           label, and a denied trace differed from a delivered one by an 18×23 px region. The
           label layer is told which host carries the trace's ending so it can move out of the way
           AND carry the state in words and a glyph, instead of leaving it to a colour behind a box.
           The KIND travels with it: the canvas has ONE alarm channel and the trace has THREE
           endings, so the word is decided here, where the verdict's band is still known. The cut
           point travels separately because it is a different claim about the same host. */
        alarm={labelAlarm}
        cutPointId={cutPointId}
        strandedIds={strandedIds}
        coordinateSpace="canvas"
      />

      <div className="fabric3d__hud">
        <span
          className="fabric3d__quality"
          data-degraded={degraded ? "true" : "false"}
          data-over-budget={breach !== null ? "true" : "false"}
          title={qualityTitle}
        >
          <span className="fabric3d__quality-dot" aria-hidden="true" />
          Quality {tierLabel}
          {breach !== null && (
            <span className="fabric3d__quality-breach">
              {" · "}
              {breach.calls}/{breach.budget} draw calls
            </span>
          )}
        </span>
        <button
          type="button"
          className="fabric3d__btn"
          /* commands.ts activates the control the mouse would, so the palette and the `r` binding
             cannot drift into doing something different from this button. */
          data-atlas-command="fabric.resetCamera"
          onClick={resetView}
        >
          Reset view
        </button>
        {/* A11Y AUDIT FIX, 2026-09-21 (D6). This button is a SCREEN toggle, not an availability
            toggle, and the difference was not stated anywhere a reader could find it.
            Measured (review/_audit_a11y_d3b.mjs): with the panel closed it reports
            aria-pressed="false" while all 31 treeitems are still in the accessibility tree. That
            is deliberate and it is the whole D6 answer — the tree is the canvas's permanent DOM
            equivalent, so it must never be gated behind a control the reader has to find first
            (see FabricA11yTree.tsx and the clip rule in Fabric3D.css, which is the standard
            visually-hidden recipe rather than a 1px accident). But a reader who meets a full
            device tree while the control that names it says "not pressed" has been handed a
            contradiction, so the arrangement is now said out loud instead of inferred.

            A description rather than a renamed label: the accessible name stays exactly the
            visible words, which is what SC 2.5.3 is about and what lets the voice-control user
            say "Fabric list". */}
        <button
          type="button"
          className="fabric3d__btn"
          aria-pressed={treeVisible}
          aria-describedby={treeNoteId}
          data-atlas-command="fabric.toggleTree"
          onClick={() => setTreeVisible((v) => !v)}
        >
          Fabric list
        </button>
        <span className="visually-hidden" id={treeNoteId}>
          The fabric list is always readable by a screen reader, whether or not it is shown. This
          shows it on screen as well.
        </span>
      </div>

      {sceneError === null ? null : (
        <div className="fabric3d__fallback" role="alert" data-testid="fabric3d-fallback">
          <h2 className="fabric3d__fallback-title">3-D fabric unavailable</h2>
          <p>
            The renderer could not start: {sceneError}. The fabric list below holds the same
            devices, links and tiers, and every one of them is still selectable. Nothing about the
            network has been hidden — only the 3-D drawing of it is missing.
          </p>
        </div>
      )}

      <FabricLegend id={legendId} devices={devices} links={links} />

      <FabricA11yTree
        devices={devices}
        links={links}
        tiers={tiers}
        visible={treeVisible || sceneError !== null}
        onHide={() => setTreeVisible(false)}
        onFocusDevice={focusDevice}
      />

      <p id={helpId} className="fabric3d__sr-only">
        Three-dimensional fabric view. Arrow keys move the selection to the nearest device in that
        direction on screen. Enter frames the camera on the selected device. Escape clears the
        selection. Home frames the whole fabric. Plus and minus zoom. The Fabric list button opens
        an equivalent tree of tiers, devices and links that does not require the canvas.
      </p>
      <div className="fabric3d__sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </div>
  );
}

function applyPick(r: PickResult | null): void {
  const st = useInvestigation.getState();
  if (r === null) {
    // Clicking the ground is an explicit "nothing", and it clears both. It does not reset the
    // camera, the query or the trace: selection re-aims the investigation, it never restarts it.
    st.selectDevice(null);
    st.selectLink(null);
    return;
  }
  if (r.kind === "device") st.selectDevice(r.id, { surface: "fabric" });
  else st.selectLink(r.id);
}

export default Fabric3D;
