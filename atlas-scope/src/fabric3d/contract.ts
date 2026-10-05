/**
 * contract.ts — the interface every part of the 3-D subsystem implements against.
 *
 * The subsystem is deliberately imperative and framework-free: React owns the DOM and the
 * investigation state, three.js owns the canvas, and this contract is the only place they meet.
 * That boundary is what keeps the render loop off React's critical path — a re-render of the
 * evidence pane must never cost a dropped frame in the fabric, and a camera tween must never
 * schedule React work. It is also what keeps the INP budget honest: input goes straight to the
 * scene handle, not through a reconciler.
 *
 * FROZEN. Implementations import from here; they do not edit it.
 */
import type { Device, Link, Trace } from "../core/types";

/* ── layout (implemented by layout.ts) ─────────────────────────────────────── */

export interface NodePosition {
  id: string;
  x: number;
  y: number;
  z: number;
  tier: number;
}

export interface CameraFraming {
  position: [number, number, number];
  target: [number, number, number];
}

export interface LayoutResult {
  nodes: NodePosition[];
  byId: ReadonlyMap<string, NodePosition>;
  /** Y plane and X/Z extent of each tier, so tier labels and ground planes can be drawn. */
  tierBounds: { tier: number; y: number; minX: number; maxX: number; minZ: number; maxZ: number; count: number }[];
  bounds: { min: [number, number, number]; max: [number, number, number] };
  framing: CameraFraming;
  /** For links spanning non-adjacent tiers: a mid-point so the cable arcs around, not through. */
  linkMidpoints: ReadonlyMap<string, [number, number, number]>;
}

/* ── scene handle (implemented by scene.ts, consumed by Fabric3D.tsx) ──────── */

export type QualityTier = "high" | "balanced" | "low";

export interface SceneOptions {
  devices: Device[];
  links: Link[];
  layout: LayoutResult;
  /** Read once at construction; theme changes go through setTheme. */
  theme: "dark" | "light";
  reducedMotion: boolean;
  /** Caller-provided override; when omitted the scene auto-selects from a capability probe. */
  quality?: QualityTier;
}

export interface PickResult {
  kind: "device" | "link";
  id: string;
  /** Screen-space position of the picked object's anchor, for placing an HTML label over it. */
  screen: { x: number; y: number };
}

export interface SceneStats {
  fps: number;
  frameMs: number;
  drawCalls: number;
  triangles: number;
  programs: number;
  quality: QualityTier;
  /** True once the progressive-refinement passes have converged, so a screenshot is meaningful. */
  converged: boolean;
}

export interface HighlightState {
  /** Hosts to emphasise; everything else recedes rather than disappearing. */
  hosts: string[];
  links: string[];
  /** The failing element in a trace or blast analysis, drawn with the alarm treatment. */
  blockedHost: string | null;
  blockedLink: string | null;
}

export interface FabricScene {
  /** Replace the data. Must reuse GPU resources where the topology is unchanged. */
  setData(devices: Device[], links: Link[], layout: LayoutResult): void;
  /** Selection is the strong state: one device or link reads as chosen, others dim. */
  setSelection(deviceId: string | null, linkId: string | null): void;
  /** Hover is the weak state: it must never move the camera or change layout. */
  setHover(deviceId: string | null, linkId: string | null): void;
  /** Emphasis without selection — used by filters and the blast-radius overlay. */
  setHighlight(h: HighlightState | null): void;
  /**
   * Draw a forwarding trace as an animated path. null clears it. Only a NEW PICTURE — compared by
   * content, never by object — draws on, runs the packet and frames the camera: the same trace re-sent
   * with another `activeHop` (every hop step), or a new object of the same answer (a history step, a
   * re-run), changes nothing on the canvas, because the active hop is shown by the selection the shell
   * re-aims to its host (design-brief.md §4.8, acceptance C6).
   */
  setTrace(trace: Trace | null, activeHop: number | null): void;
  /** Ease the camera to frame one device and its neighbours. Respects reducedMotion. */
  focusDevice(deviceId: string | null, opts?: { immediate?: boolean }): void;
  /** Frame the entire fabric. */
  resetCamera(opts?: { immediate?: boolean }): void;
  setTheme(theme: "dark" | "light"): void;
  setQuality(q: QualityTier): void;
  resize(width: number, height: number): void;
  /** Hit-test a client-space point; used for click, and for keyboard-driven selection readout. */
  pick(clientX: number, clientY: number): PickResult | null;
  /** Project a host's anchor to screen space so React can position an HTML label. */
  project(deviceId: string): { x: number; y: number; visible: boolean } | null;
  stats(): SceneStats;
  /** Stop the loop and release every GPU resource. Must be idempotent. */
  dispose(): void;
}

export type SceneEvent =
  | { type: "pick"; result: PickResult | null; modifier: boolean }
  | { type: "hover"; result: PickResult | null }
  | { type: "camera"; settled: boolean }
  | { type: "stats"; stats: SceneStats };

export interface SceneCallbacks {
  onEvent(e: SceneEvent): void;
}

/** The single entry point scene.ts must export. */
export type CreateScene = (
  canvas: HTMLCanvasElement,
  opts: SceneOptions,
  cb: SceneCallbacks,
) => FabricScene;
