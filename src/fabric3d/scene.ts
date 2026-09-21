/**
 * scene.ts — the three.js subsystem's only entry point.
 *
 * `createScene` owns the renderer, the scene graph, the render loop and every GPU resource behind
 * them. React never touches any of it: it hands data in and receives events out, which is what
 * keeps a re-render of the evidence pane off the fabric's critical path and the fabric off React's
 * (contract.ts states that boundary; this file is the half that honours it).
 *
 * The loop is IDLE BY DEFAULT. A still camera over unchanged state renders nothing at all: a frame
 * is drawn only when something has actually changed, and the tab being hidden stops it outright.
 * An investigation that sits open for twenty minutes should cost no GPU, and "60 fps" on a static
 * image is not a feature, it is a fan.
 *
 * Nothing in the draw path calls `Math.random()` or `Date.now()`. Animation is driven by
 * `performance.now()` deltas, and every animation both TERMINATES and terminates at a value that
 * depends on its target rather than on the frame timing it happened to get — which is the property
 * acceptance F6 actually needs and the one this file got wrong: recession used to freeze at the
 * last eased value, so two capture runs differed in 22 of 32 PNGs. The easing state machine now
 * lives in `./emphasis`, where it is stepped by a test with deliberately unequal `dt` sequences,
 * and `converged()` defers to the same module's `isConverged`.
 *
 * `buildFabricGraph` is exported alongside the contract entry point because the entire scene-graph
 * assembly — geometry, materials, instancing, the layout-to-object mapping — needs no WebGL context
 * and is therefore testable for real in jsdom. Only the renderer, the environment prefilter and the
 * composer need a GPU, and those are the three things scene.test.ts is honest about not covering.
 */
import {
  BoxGeometry,
  Color,
  DynamicDrawUsage,
  InstancedBufferAttribute,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  NoToneMapping,
  Object3D,
  Quaternion,
  SRGBColorSpace,
  Scene,
  Vector3,
  WebGLRenderer,
  PCFShadowMap,
  type BufferGeometry,
  type Material,
} from "three";
import type { Camera } from "three";
import type { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import type { Device, Link, Trace } from "../core/types";
import { createCameraRig, frameSphereFromCurrentView, type CameraRig } from "./camera";
import type {
  CreateScene,
  FabricScene,
  HighlightState,
  LayoutResult,
  PickResult,
  QualityTier,
  SceneCallbacks,
  SceneOptions,
  SceneStats,
} from "./contract";
import {
  RECEDE_DEPTH,
  RECEDE_NEIGHBOUR,
  createEmphasisState,
  isConverged,
  markEmphasisDirty,
  stepEmphasis,
  type EmphasisState,
} from "./emphasis";
import {
  createBackdrop,
  createEnvironment,
  prepareEnvironment,
  type EnvironmentHandle,
  type EnvironmentPrefilter,
} from "./env";
import { createFlowOverlay, type FlowOverlay } from "./flow";
import {
  buildChassis,
  buildRoleGlyph,
  buildStateRing,
  chassisSilhouette,
  chassisSpec,
  normaliseKind,
  unitDecal,
  type ChassisKind,
  type ChassisParts,
  type RoleGlyph,
  type StateRingShape,
} from "./geometry/chassis";
import { buildCables, createCableMaterial, type CableSet } from "./geometry/cables";
import { DECK_DROP, Y_HALO, Y_STATE_RING, buildGround, type GroundSet } from "./geometry/ground";
import { createInteraction, PICK_LAYER, type Interaction } from "./interaction";
import { createLighting } from "./lighting";
import {
  RECEDE_ATTRIBUTE,
  buildMaterials,
  buildProceduralMaps,
  checkAuthoringBands,
  readTokens,
  retintMaterials,
  type MaterialLibrary,
  type ProceduralMaps,
  type TokenPalette,
} from "./materials";
import { createPostChain, type PostChain } from "./postfx";
import {
  chooseQuality,
  probeCapabilities,
  profileFor,
  type QualityDecision,
  type QualityProfile,
} from "./quality";
import type { FabricLayout, FabricTierBounds } from "./layout";

/**
 * Draw-call budget for one COMPOSED frame, asserted after every render.
 *
 * ── WHY THIS IS NOT ONE NUMBER ──────────────────────────────────────────────────────────────────
 *
 * It was 120 — a single flat ceiling — and the product breached it permanently and silently the
 * moment a path trace was on screen. That is not a rounding error in the number; it is the wrong
 * SHAPE of number. A composed frame here is not one cost. It is a base cost plus a surcharge for
 * each `OutlineEffect` that currently has something selected, because `OutlineEffect.update()`
 * re-renders the WHOLE scene into a depth buffer and then renders the selection into a mask
 * (postprocessing 6.39.5, `OutlineEffect.js`: `depthPass.render` + `maskPass.render`, guarded by
 * `selection.size > 0`). One flat ceiling cannot describe both frames: set it where the idle frame
 * lives and every traced frame breaches; set it where the traced frame lives and the idle frame
 * could double in cost without tripping anything.
 *
 * So the budget is the model, not a single reading. It tightens the idle frame (74 measured
 * against 88, where it used to be measured against 120) AND stops lying about the traced one.
 *
 * ── THE MEASUREMENT ─────────────────────────────────────────────────────────────────────────────
 *
 * Re-measured 2026-09-21, dev server, ANGLE → Intel D3D11, 1920×1080, `high`, `converged: true`,
 * 30 consecutive rAF samples per state, `min === max` in every row (steady state, not a
 * rebuild transient). Each row names the state it was taken in, because the previous version of
 * this comment generalised one state's reading to "a real frame" and that is how the breach hid:
 *
 *   nothing selected, no trace          74 calls / 240,982 tris   0 outline effects active
 *   device selected                    103 calls / 332,415 tris   1 (selection outline)
 *   trace DELIVERED (`tcp/443`)        103 calls / 332,415 tris   1
 *   trace DENIED (`tcp/3389`)          141 calls / 425,616 tris   2 (+ blocked outline)
 *   trace INDETERMINATE                141 calls / 425,616 tris   2
 *   denied trace AND a device selected 141 calls / 425,616 tris   2  ← the ceiling of the design
 *
 * The deltas are the model: +29 for the selection outline (full-scene depth pass + mask), +38 for
 * the blocked outline (the same, plus the Kawase blur it alone enables). The trace geometry itself
 * costs ZERO extra calls — the delivered row is identical to the plain-selection row — so the
 * whole of the +67 a traced frame used to "cost" is the second outline effect, not the trace.
 *
 * Earlier readings, kept because they are the reason this is written down: "124 calls at high" was
 * the FIRST frame after a post-chain rebuild, in which each `OutlineEffect` runs its depth+mask
 * pass once (`forceUpdate = true` in its constructor). `renderer.info` holds the last RENDERED
 * frame and an idle scene does not render, so that transient could be read back minutes later and
 * looked like a steady state.
 *
 * ── HOW A BREACH IS REPORTED ────────────────────────────────────────────────────────────────────
 *
 * Reported through `stats().overBudget` and `stats().drawCallBudget` rather than thrown: a blank
 * canvas is a worse failure than a slow one. It takes TWO consecutive rendered frames over the
 * ceiling, so the one-off rebuild frame above is not called a standing breach — and a standing
 * breach cannot be dismissed as a transient. The dev console names every breaching frame; the
 * quality chip in `Fabric3D.tsx` shows a STANDING breach in every build, dev or production,
 * because "degradation is explicit, never silent" (acceptance E4) is worth nothing if the only
 * report is stripped out of the bundle that ships.
 */

/** A composed frame with no outline effect active. Measured 74 at `high`; 14 calls of headroom. */
export const DRAW_CALL_BUDGET_BASE = 88;

/**
 * What one `OutlineEffect` with a non-empty selection is allowed to add.
 *
 * Measured +29 (selection outline) and +38 (blocked outline, which also runs a Kawase blur). The
 * budget is one number for both because the chain may run either, and the larger measurement is
 * the one a ceiling has to survive.
 */
export const DRAW_CALL_BUDGET_PER_OUTLINE = 44;

/**
 * Outline effects the post chain can run at once — see `postfx.ts`, which builds exactly two
 * (`selectionOutline`, `blockedOutline`). `layers.test.ts` asserts this against the registry so a
 * third one cannot be added without the published ceiling moving with it.
 */
export const OUTLINE_EFFECT_COUNT = 2;

/**
 * The ceiling of the whole design: the base frame with every outline effect active at once. This
 * is the number design-brief.md §4.4 publishes, and `layers.test.ts` asserts the two agree.
 */
export const DRAW_CALL_BUDGET = DRAW_CALL_BUDGET_BASE + OUTLINE_EFFECT_COUNT * DRAW_CALL_BUDGET_PER_OUTLINE;

/**
 * The budget that applies to a frame with `activeOutlines` outline effects currently selecting
 * something. Exported so a test can check the model rather than re-deriving it.
 */
export function drawCallBudgetFor(activeOutlines: number): number {
  const clamped = Math.max(0, Math.min(OUTLINE_EFFECT_COUNT, activeOutlines));
  return DRAW_CALL_BUDGET_BASE + clamped * DRAW_CALL_BUDGET_PER_OUTLINE;
}

/** Consecutive rendered frames over the frame's budget before the breach is called standing. */
const OVER_BUDGET_FRAMES = 2;

/**
 * The shadow filter this scene intends, asserted after assignment at construction.
 *
 * See the comment at the assignment site: design-brief.md §4.3 names PCFSoftShadowMap, which three
 * 0.186.0 removed and silently substitutes. Naming the intent in one place is what lets the
 * assertion exist at all.
 */
export const INTENDED_SHADOW_MAP_TYPE = PCFShadowMap;

/**
 * Adaptive degradation. Frame time is a measurement; the tier it implies is a decision, and the
 * decision is announced in `stats().qualityReasons` rather than made quietly. Only ever steps
 * DOWN — an automatic step back up would oscillate around the threshold, which is worse than
 * running one tier below optimal.
 */
const SLOW_FRAME_MS = 24;
const SLOW_FRAMES_BEFORE_STEP = 45;

/**
 * How long a bad frame stays visible in `stats().worstFrameMs`.
 *
 * One second, which is two of the 500 ms stats emits: long enough that a reader who asks right
 * after a stutter is told about it, short enough that "the worst frame" still means "recently"
 * rather than "at some point since the page loaded".
 */
const WORST_FRAME_WINDOW_MS = 1000;

/**
 * Ceiling on the cold-load warm-up's parallel-link wait, in milliseconds.
 *
 * The warm-up yields between every stage and never blocks on a link (see advanceWarmup), so the
 * only thing this bounds is how long the fabric may stay unpainted if a driver never reports a
 * program as ready. Past it the loop renders anyway — which costs the old blocking stall once, and
 * is still better than a canvas that never draws. Measured link waits on the reference machine are
 * 1.3-2.0 s, so 10 s is about five times the observed worst case: a stuck-driver backstop, not a
 * schedule.
 */
const WARMUP_LINK_DEADLINE_MS = 10000;

/* The recession window, depth and epsilon live in ./emphasis alongside the state machine that
   reads them — that module is the half of the animation whose final value ends up in a capture,
   and it was extracted so it can be stepped by a test without a GPU. */
const HOVER_MS = 80;
const SELECT_MS = 140;

/**
 * Label thinning, by COLLISION rather than by threshold.
 *
 * design-brief.md §4.4 drops labels "by count, not by opacity" below a dolly factor. Dropping by
 * count is exactly right — opacity fading produces the muddy half-legible text that reads as
 * unfinished — but a dolly factor is a proxy for the thing that actually matters, which is whether
 * two labels overlap. Measured at 1440x900: the dolly factor is 1.0 and eight labels collide.
 *
 * So the scene projects every anchor, orders the candidates by how much the user needs each one,
 * and keeps a label only when its box clears every box already kept. That drops the minimum number
 * of labels rather than a fixed tier of them, and it is stable: the ordering is deterministic and
 * the camera is still whenever a capture is taken.
 *
 * The glyph metrics are an ESTIMATE — 11 px Inter at weight 500 averages close to 6.1 px per
 * character — because the scene cannot measure a font it does not own. The estimate errs wide, so
 * the failure mode is one label too few rather than two labels overlapping.
 */
const LABEL_CHAR_PX = 6.1;
const LABEL_PAD_PX = 10;
const LABEL_LINE_PX = 15;
/** Vertical gap between a label's box and the anchor it belongs to. */
const LABEL_RISE_PX = 4;

export interface SceneStatsEx extends SceneStats {
  /**
   * The slowest single frame in the last `WORST_FRAME_WINDOW_MS`, in milliseconds, unclamped.
   *
   * `frameMs` is the last frame and `fps` is a slow EMA; both of them average a catastrophic frame
   * away within a second of it happening. This one cannot: it is a maximum over the reporting
   * window, and it is the figure a frame-rate claim has to survive. Reported separately rather than
   * folded into `frameMs` because "the last frame" and "the worst frame" are different questions
   * and a reader is entitled to both.
   */
  worstFrameMs: number;
  /** Why this quality tier is in force. Non-empty even at `high` — degradation is never silent. */
  qualityReasons: string[];
  qualityAuto: boolean;
  /**
   * True when this frame's draw-call ceiling has been breached for `OVER_BUDGET_FRAMES`
   * consecutive rendered frames — a STANDING breach, not a rebuild transient. Surfaced in the
   * quality chip in every build; see the `DRAW_CALL_BUDGET` comment for why it is not thrown.
   */
  overBudget: boolean;
  /**
   * The ceiling that applied to the frame `drawCalls` was read from — `drawCallBudgetFor(n)` with
   * `n` outline effects currently selecting something. Reported next to `drawCalls` so a reader is
   * never left comparing a measurement against a budget they have to guess at.
   */
  drawCallBudget: number;
  /** Outline effects with a non-empty selection in the reported frame. 0, 1 or 2. */
  activeOutlines: number;
  /** Tokens the stylesheet did not declare, which fell back to the brief's published values. */
  missingTokens: string[];
  /** Hop pairs a trace could not draw because the snapshot holds no cable between them. */
  undrawnHops: string[];
  /**
   * How many device labels survived collision resolution, out of how many devices. Reported so a
   * DOM overlay can say "12 of 26 labelled" instead of leaving the user to guess whether the
   * unlabelled nodes are unnamed or merely crowded.
   */
  labelsShown: number;
  labelsTotal: number;
  /**
   * The cold-load warm-up stage this reading was taken in, or null once the scene is drawing.
   *
   * Published because the warm-up is the one piece of work in this subsystem that is allowed to
   * take seconds (acceptance E5), and work that is allowed to be slow has to be visible while it
   * is happening — otherwise a reader looking at an unpainted stage cannot tell "building" from
   * "broken".
   */
  warmupStage: WarmupStage | null;
  /** Shader programs that have finished linking, out of how many have been handed to the driver. */
  programsLinked: number;
  programsTotal: number;
  /** True when the link wait hit WARMUP_LINK_DEADLINE_MS and the loop drew without waiting. */
  warmupTimedOut: boolean;
  /**
   * How many frames have had their DURATION measured.
   *
   * The denominator for `fps`, `frameMs` and `worstFrameMs`: at 0 those three are not slow, not
   * fast and not a measurement — nothing has been timed. One rAF callback yields a timestamp
   * with nothing to subtract it from, so the count starts at the SECOND frame.
   *
   * Published because the alternative is a reader inferring it. Measured before this existed
   * (review/_audit_perf_fpsema.mjs): the scene reported 60 fps with 0 draw calls and 0 programs
   * linked while the canvas was blank and the next frame took 483 ms.
   */
  framesTimed: number;
}

/**
 * The stages of the cold-load warm-up, in order. Each owns at most one animation frame and then
 * yields; "linking" owns none at all — it polls and returns.
 */
export type WarmupStage =
  | "yield"
  | "environment-programs"
  | "environment"
  | "scene-programs"
  | "post-programs"
  | "linking"
  | "passes";

/* ── scene graph ───────────────────────────────────────────────────────────── */

interface KindGroup {
  kind: ChassisKind;
  parts: ChassisParts;
  /** Geometry clones owned by this group and disposed with it. */
  owned: BufferGeometry[];
  solidIds: string[];
  ghostIds: string[];
  meshes: InstancedMesh[];
  body: InstancedMesh | null;
  led: InstancedMesh | null;
  ghost: InstancedMesh | null;
  recede: InstancedBufferAttribute | null;
  ghostRecede: InstancedBufferAttribute | null;
  /** Untouched copy of the body geometry, for the outline proxies. */
  proxyGeometry: BufferGeometry;
}

interface DeviceSlot {
  id: string;
  device: Device;
  kind: ChassisKind;
  group: KindGroup;
  /** Index into the solid or ghost instance array. */
  slot: number;
  ghost: boolean;
  /** World centre of the chassis body (NOT the layout node centre — the chassis sits on the deck). */
  centre: [number, number, number];
  half: [number, number, number];
  top: number;
  /** Global index, shared by the pick proxy, the contact decals and the recession arrays. */
  index: number;
}

export interface FabricGraph {
  scene: Scene;
  groups: Map<ChassisKind, KindGroup>;
  slots: Map<string, DeviceSlot>;
  order: DeviceSlot[];
  cables: CableSet;
  ground: GroundSet;
  pickProxy: InstancedMesh;
  pickIds: string[];
  roleGlyphs: InstancedMesh[];
  stateRings: InstancedMesh[];
  hatch: InstancedMesh | null;
  ghostEdges: LineSegments2 | null;
  halo: Mesh;
  hoverShell: Mesh;
  selectionProxy: Mesh;
  blockedProxy: Mesh;
  materials: MaterialLibrary;
  maps: ProceduralMaps;
  tokens: TokenPalette;
  /** Signature of the topology this graph was built from, so setData can skip a rebuild. */
  signature: string;
  neighbours: Map<string, string[]>;
  linkEnds: Map<string, { a: string; b: string }>;
  emissiveObjects: Object3D[];
  dispose(): void;
}

const _m = new Matrix4();
const _pos = new Vector3();
const _scale = new Vector3();
const _rot = new Quaternion();
const _colour = new Color();
const _world = new Vector3();
const AXIS_X = new Vector3(1, 0, 0);

const ROLE_GLYPHS: readonly RoleGlyph[] = ["access", "distribution", "unobserved"];
const RING_SHAPES: readonly StateRingShape[] = ["solid", "dashed", "double"];

function topologySignature(devices: readonly Device[], links: readonly Link[]): string {
  const d = devices.map((x) => `${x.id}/${x.kind}/${x.collected ? 1 : 0}`).join(",");
  const l = links.map((x) => `${x.id}:${x.a}>${x.b}`).join(",");
  return `${d}|${l}`;
}

function roleGlyphFor(role: string | null): RoleGlyph {
  if (role === "access") return "access";
  if (role === "distribution") return "distribution";
  // Every other value, `null` included, gets the OUTLINED mark. 17 of 26 devices in this snapshot
  // carry role: null, and rendering nothing for them would be indistinguishable from a bug.
  return "unobserved";
}

function ringShapeFor(status: string): StateRingShape {
  if (status === "up") return "solid";
  if (status === "down") return "double";
  return "dashed";
}

/**
 * How far the chassis BODY's band tint is mixed toward white.
 *
 * Was 0.72, which left the encoding carrying nothing: measured on a real GPU at `high` in dark
 * theme (review/_audit_bandcolour.mjs samples the brightest 6 % of each device's projected box),
 * Poor read #bdbabb and Critical #bbb6b9 — three levels apart, against a within-Poor spread of
 * about fifteen levels across access1..access12. A device the snapshot calls Critical rendered the
 * same colour as one it calls Excellent.
 *
 * 0.40, and the reason it is not lower is a measurement too, not restraint. Sweeping the mix down
 * to 0.0 — the raw token, no wash at all — moves Poor vs Critical by three levels and no further:
 *
 *   mix   Poor        Critical    Good        Excellent
 *   0.72  189,186,187 187,182,185 174,179,177 178,184,185
 *   0.55  187,183,182 186,179,180 170,176,171 173,183,181
 *   0.40  186,182,178 183,178,175 163,174,165 169,181,178
 *   0.25  182,181,175 179,177,172 159,172,160 162,181,175
 *   0.00  180,180,171 177,175,167 154,169,151 156,180,172
 *
 * The body face this is read on is the LIT LID, and at that luminance AgX's shoulder compresses
 * chroma hard — which is what AgX is for. `--band-poor` (#ff9f45) and `--band-critical` (#ff6b6b)
 * differ only in green and blue, and both are being asked to survive on a surface that renders
 * near 185/255. They cannot, at any mix. Below 0.40 the chassis starts to read as painted plastic
 * while Poor and Critical are still three levels apart, so the extra chroma buys nothing.
 *
 * The band is therefore carried on a SECOND channel that can hold it — the status LED, whose
 * material is emissive-driven from the instance colour and sits on a near-black recess where
 * nothing is compressed. See `bandEmissive` and the call sites.
 */
const BAND_BODY_WASH = 0.4;

/**
 * The band at its true hue, for the emissive channel.
 *
 * `materials.led` is built with `emissiveFromInstanceColor`, so this colour becomes RADIANCE on a
 * near-black strip rather than albedo on a blown-out lid. That is the difference between an
 * encoding and a decoration.
 *
 * The call site used to be `bandTint(...).multiplyScalar(1.4)` under a comment claiming the LED
 * "carries the band at FULL saturation". It did not: it carried the body's 72 %-white wash,
 * brightened — the one channel with the headroom to distinguish the five bands was spending it on
 * a colour that had already been thrown away.
 */
function bandEmissive(band: string | null, tokens: TokenPalette, out: Color): Color {
  return bandTint(band, tokens, out, 0).multiplyScalar(1.4);
}

/**
 * The band tint carried by the chassis body.
 *
 * Mixed toward white so the multiply against the body albedo shifts the hue without painting the
 * hardware. Chroma in this product is spent on severity and state; a fully saturated chassis would
 * make the furniture louder than a Critical finding, which §3.3 forbids outright.
 * `band === null` renders as `--claim-indeterminate` — never neutral grey, which reads as disabled,
 * and never `--band-good`, which would be an invented verdict.
 */
function bandTint(band: string | null, tokens: TokenPalette, out: Color, wash = BAND_BODY_WASH): Color {
  const token =
    band === null
      ? "--claim-indeterminate"
      : band === "Excellent"
        ? "--band-excellent"
        : band === "Good"
          ? "--band-good"
          : band === "Fair"
            ? "--band-fair"
            : band === "Poor"
              ? "--band-poor"
              : "--band-critical";
  return out.copy(tokens.color(token)).lerp(new Color(1, 1, 1), wash);
}

function stateTint(status: string, tokens: TokenPalette, out: Color): Color {
  const token = status === "up" ? "--state-up" : status === "down" ? "--state-down" : "--state-unknown";
  return out.copy(tokens.color(token));
}

export interface BuildGraphOptions {
  devices: readonly Device[];
  links: readonly Link[];
  layout: LayoutResult;
  theme: "dark" | "light";
  profile: QualityProfile;
  /** Override for tests; defaults to the live stylesheet on document.documentElement. */
  tokenRoot?: Element;
}

/**
 * Assemble the whole scene graph. No renderer, no WebGL context, no clock — which is what makes it
 * testable, and also what makes it safe to call again on a data change without tearing the loop
 * down first.
 */
export function buildFabricGraph(opts: BuildGraphOptions): FabricGraph {
  const { devices, links, profile } = opts;
  const layout = opts.layout as FabricLayout;
  const tokens = readTokens(opts.theme, opts.tokenRoot);
  const maps = buildProceduralMaps(profile.anisotropy);
  // One repeat per hatch decal would give three enormous stripes; three repeats reads as hatching
  // at the size a chassis lid actually occupies on screen.
  maps.hatch.repeat.set(3, 3);
  const materials = buildMaterials({ tokens, maps });
  retintMaterials(materials, tokens);

  const scene = new Scene();
  scene.name = "fabric";

  /* Devices are bucketed by kind, then by whether the collector reached them. An uncollected
     device is NOT dropped and NOT greyed out: it is drawn as the same silhouette in a translucent
     shell with a wireframe edge and a 45-degree hatch on its lid, which says "this is topology we
     were told about but never observed" and cannot be mistaken for either healthy or absent. */
  const groups = new Map<ChassisKind, KindGroup>();
  const slots = new Map<string, DeviceSlot>();
  const order: DeviceSlot[] = [];

  const placed = devices.filter((d) => layout.byId.has(d.id));

  for (const device of placed) {
    const kind = normaliseKind(device.kind);
    let group = groups.get(kind);
    if (group === undefined) {
      const parts = buildChassis(kind, {
        bevelSegments: profile.chassisBevelSegments,
        fineDetail: profile.chassisFineDetail,
      });
      group = {
        kind,
        parts,
        owned: [],
        solidIds: [],
        ghostIds: [],
        meshes: [],
        body: null,
        led: null,
        ghost: null,
        recede: null,
        ghostRecede: null,
        proxyGeometry: parts.body.clone(),
      };
      groups.set(kind, group);
    }
    if (device.collected) group.solidIds.push(device.id);
    else group.ghostIds.push(device.id);
  }

  let globalIndex = 0;
  for (const group of groups.values()) {
    const spec = chassisSpec(group.kind);
    const half: [number, number, number] = [...group.parts.half];

    const makeInstanced = (
      geometry: BufferGeometry,
      material: Material,
      ids: string[],
      recede: InstancedBufferAttribute,
      name: string,
    ): InstancedMesh => {
      geometry.setAttribute(RECEDE_ATTRIBUTE, recede);
      const mesh = new InstancedMesh(geometry, material, Math.max(1, ids.length));
      mesh.name = name;
      mesh.count = ids.length;
      mesh.castShadow = profile.shadows;
      mesh.receiveShadow = profile.shadows;
      // One batch spans the fabric; per-object culling would only ever cull the whole thing.
      mesh.frustumCulled = false;
      mesh.instanceMatrix.setUsage(DynamicDrawUsage);
      return mesh;
    };

    if (group.solidIds.length > 0) {
      const recede = new InstancedBufferAttribute(new Float32Array(group.solidIds.length), 1);
      recede.setUsage(DynamicDrawUsage);
      group.recede = recede;

      const body = makeInstanced(group.parts.body, materials.body, group.solidIds, recede, `${group.kind}:body`);
      const bezel = makeInstanced(group.parts.bezel, materials.bezel, group.solidIds, recede, `${group.kind}:bezel`);
      const dark = makeInstanced(group.parts.dark, materials.dark, group.solidIds, recede, `${group.kind}:dark`);
      const rail = makeInstanced(group.parts.rail, materials.rail, group.solidIds, recede, `${group.kind}:rail`);
      const led = makeInstanced(group.parts.led, materials.led, group.solidIds, recede, `${group.kind}:led`);
      led.castShadow = false;
      group.body = body;
      group.led = led;
      group.meshes.push(body, bezel, dark, rail, led);
      for (const m of group.meshes) scene.add(m);
    }

    if (group.ghostIds.length > 0) {
      const ghostGeometry = group.parts.body.clone();
      group.owned.push(ghostGeometry);
      const recede = new InstancedBufferAttribute(new Float32Array(group.ghostIds.length), 1);
      recede.setUsage(DynamicDrawUsage);
      group.ghostRecede = recede;
      const ghost = makeInstanced(ghostGeometry, materials.ghost, group.ghostIds, recede, `${group.kind}:ghost`);
      // A shell we never observed must not cast a shadow: a shadow is evidence of a solid object,
      // and we have no evidence this one is there at all.
      ghost.castShadow = false;
      ghost.receiveShadow = false;
      ghost.renderOrder = 3;
      group.ghost = ghost;
      scene.add(ghost);
    }

    const place = (ids: string[], ghost: boolean): void => {
      for (let i = 0; i < ids.length; i += 1) {
        const id = ids[i];
        if (id === undefined) continue;
        const node = layout.byId.get(id);
        const device = placed.find((d) => d.id === id);
        if (node === undefined || device === undefined) continue;
        const deckTop = node.y - DECK_DROP;
        const centre: [number, number, number] = [node.x, deckTop + spec.height / 2, node.z];
        const s: DeviceSlot = {
          id,
          device,
          kind: group.kind,
          group,
          slot: i,
          ghost,
          centre,
          half,
          top: deckTop + spec.height,
          index: globalIndex,
        };
        globalIndex += 1;
        slots.set(id, s);
        order.push(s);
      }
    };
    place(group.solidIds, false);
    place(group.ghostIds, true);
  }

  // Instance matrices and colours, once the slot table is complete.
  for (const s of order) {
    _pos.set(s.centre[0], s.centre[1], s.centre[2]);
    _scale.set(1, 1, 1);
    _m.compose(_pos, _rot, _scale);
    const target = s.ghost ? s.group.ghost : s.group.body;
    if (s.ghost) {
      if (target !== null) target.setMatrixAt(s.slot, _m);
    } else {
      for (const mesh of s.group.meshes) mesh.setMatrixAt(s.slot, _m);
      if (s.group.body !== null) {
        s.group.body.setColorAt(s.slot, bandTint(s.device.band, tokens, _colour));
      }
      if (s.group.led !== null) {
        // The LED strip carries the band at its TRUE hue, as emission on a near-black recess, which is
        // what makes it legible at overview distance and what makes the encoding real; the body carries
        // the same band as a wash that AgX compresses away. See BAND_BODY_WASH.
        s.group.led.setColorAt(s.slot, bandEmissive(s.device.band, tokens, _colour));
      }
    }
  }
  for (const group of groups.values()) {
    for (const mesh of group.meshes) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor !== null) mesh.instanceColor.needsUpdate = true;
    }
    if (group.ghost !== null) group.ghost.instanceMatrix.needsUpdate = true;
  }

  /* Role glyphs. Three shapes, one instanced mesh each, on the chassis lid where the default
     camera can actually see them. */
  const roleGlyphs: InstancedMesh[] = [];
  for (const glyph of ROLE_GLYPHS) {
    const members = order.filter((s) => roleGlyphFor(s.device.role) === glyph);
    const geometry = buildRoleGlyph(glyph);
    const mesh = new InstancedMesh(geometry, materials.rail, Math.max(1, members.length));
    mesh.name = `role:${glyph}`;
    mesh.count = members.length;
    mesh.frustumCulled = false;
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    for (let i = 0; i < members.length; i += 1) {
      const s = members[i];
      if (s === undefined) continue;
      _pos.set(s.centre[0] - s.half[0] * 0.58, s.top + 0.05, s.centre[2] + s.half[2] * 0.3);
      _rot.setFromAxisAngle(AXIS_X, -Math.PI / 2);
      _scale.set(2.1, 2.1, 2.1);
      mesh.setMatrixAt(i, _m.compose(_pos, _rot, _scale));
    }
    _rot.identity();
    mesh.instanceMatrix.needsUpdate = true;
    roleGlyphs.push(mesh);
    scene.add(mesh);
  }

  /* Operational-state rings on the deck. Shape encodes state; colour reinforces it. Both, always —
     a greyscale capture must still distinguish up from unknown (acceptance D8). */
  const stateRings: InstancedMesh[] = [];
  for (const shape of RING_SHAPES) {
    const members = order.filter((s) => ringShapeFor(s.device.opStatus) === shape);
    const geometry = buildStateRing(shape);
    const mesh = new InstancedMesh(geometry, materials.stateRim, Math.max(1, members.length));
    mesh.name = `state:${shape}`;
    mesh.count = members.length;
    mesh.frustumCulled = false;
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    for (let i = 0; i < members.length; i += 1) {
      const s = members[i];
      if (s === undefined) continue;
      _pos.set(s.centre[0], s.centre[1] - chassisSpec(s.kind).height / 2 + Y_STATE_RING, s.centre[2]);
      _scale.set(s.half[0] * 1.42, 1, s.half[2] * 1.62);
      mesh.setMatrixAt(i, _m.compose(_pos, _rot, _scale));
      mesh.setColorAt(i, stateTint(s.device.opStatus, tokens, _colour));
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor !== null) mesh.instanceColor.needsUpdate = true;
    stateRings.push(mesh);
    scene.add(mesh);
  }

  /* Uncollected treatment: hatch on the lid, wireframe on the silhouette. */
  const ghostSlots = order.filter((s) => s.ghost);
  let hatch: InstancedMesh | null = null;
  let ghostEdges: LineSegments2 | null = null;
  if (ghostSlots.length > 0) {
    const hatchGeometry = unitDecal();
    hatch = new InstancedMesh(hatchGeometry, materials.hatch, ghostSlots.length);
    hatch.name = "uncollected-hatch";
    hatch.frustumCulled = false;
    hatch.renderOrder = 4;
    for (let i = 0; i < ghostSlots.length; i += 1) {
      const s = ghostSlots[i];
      if (s === undefined) continue;
      _pos.set(s.centre[0], s.top + 0.04, s.centre[2]);
      _scale.set(s.half[0] * 1.55, 1, s.half[2] * 1.5);
      hatch.setMatrixAt(i, _m.compose(_pos, _rot, _scale));
    }
    hatch.instanceMatrix.needsUpdate = true;
    scene.add(hatch);

    // The wireframe is baked into world space rather than instanced: three uncollected devices do
    // not justify a second instanced pipeline, and a baked batch is one draw call either way.
    const positions: number[] = [];
    for (const s of ghostSlots) {
      const edges = chassisSilhouette(s.group.parts);
      const attr = edges.getAttribute("position");
      for (let i = 0; i < attr.count; i += 1) {
        positions.push(attr.getX(i) + s.centre[0], attr.getY(i) + s.centre[1], attr.getZ(i) + s.centre[2]);
      }
      edges.dispose();
    }
    if (positions.length >= 6) {
      const geometry = new LineSegmentsGeometry();
      geometry.setPositions(new Float32Array(positions));
      const lineMaterial = buildGhostLineMaterial(tokens);
      ghostEdges = new LineSegments2(geometry, lineMaterial);
      ghostEdges.name = "uncollected-edges";
      ghostEdges.frustumCulled = false;
      ghostEdges.renderOrder = 4;
      scene.add(ghostEdges);
    }
  }

  /* Cables. */
  const cables = buildCables({
    links,
    anchorOf(host: string) {
      const s = slots.get(host);
      if (s === undefined) return null;
      return { centre: s.centre, half: s.half };
    },
    midpointOf(linkId: string) {
      return layout.linkMidpoints.get(linkId) ?? null;
    },
    segments: profile.cableSegments,
    tokens,
  });
  for (const batch of cables.batches) scene.add(batch.object);

  /* Ground, decks, contact shadows. */
  const ground = buildGround({
    tierBounds: layout.tierBounds as FabricTierBounds[],
    bounds: layout.bounds,
    nodes: order.map((s) => ({ id: s.id, x: s.centre[0], y: s.centre[1] + DECK_DROP - chassisSpec(s.kind).height / 2, z: s.centre[2] })),
    footprintOf(id: string) {
      return slots.get(id)?.half ?? ([4, 2, 4] as const);
    },
    materials,
    shadows: profile.shadows,
  });
  scene.add(ground.group);

  /* Hit-test proxies, on their own layer so the camera never renders them.
   *
   * The material is this proxy's OWN invisible one, not the shared contact decal. The layer is the
   * contract, but a layer is one integer: when postprocessing allocated an outline Selection onto
   * PICK_LAYER these proxies were drawn by the outline's mask pass wearing `contact-shadow`'s black
   * — 26 black boxes with red edges over the fabric. Depth-only, colour-write-off geometry cannot
   * paint that, whoever renders it by mistake. */
  const pickGeometry = new BoxGeometry(1, 1, 1);
  const pickMaterial = invisibleMaterial();
  pickMaterial.name = "pick-proxy";
  const pickProxy = new InstancedMesh(pickGeometry, pickMaterial, Math.max(1, order.length));
  pickProxy.name = "pick-proxy";
  pickProxy.count = order.length;
  pickProxy.frustumCulled = false;
  pickProxy.layers.set(PICK_LAYER);
  const pickIds: string[] = [];
  for (let i = 0; i < order.length; i += 1) {
    const s = order[i];
    if (s === undefined) continue;
    const spec = chassisSpec(s.kind);
    _pos.set(s.centre[0], s.centre[1], s.centre[2]);
    // Slightly generous in Y so a click near the lid or the deck still lands on the device.
    _scale.set(s.half[0] * 2 + 1.5, spec.height + 3, s.half[2] * 2 + 1.5);
    pickProxy.setMatrixAt(i, _m.compose(_pos, _rot, _scale));
    pickIds.push(s.id);
  }
  pickProxy.instanceMatrix.needsUpdate = true;
  scene.add(pickProxy);

  /* Selection halo, hover shell, and the two outline proxies. */
  const haloGeometry = unitDecal();
  const halo = new Mesh(haloGeometry, materials.halo);
  halo.name = "selection-halo";
  halo.visible = false;
  halo.renderOrder = 2;
  scene.add(halo);

  const firstGroup = groups.values().next().value as KindGroup | undefined;
  const fallbackGeometry = firstGroup?.proxyGeometry ?? new BoxGeometry(1, 1, 1);

  const hoverShell = new Mesh(fallbackGeometry, materials.hoverShell);
  hoverShell.name = "hover-shell";
  hoverShell.visible = false;
  hoverShell.renderOrder = 3;
  scene.add(hoverShell);

  const selectionProxy = new Mesh(fallbackGeometry, invisibleMaterial());
  selectionProxy.name = "selection-proxy";
  selectionProxy.visible = false;
  scene.add(selectionProxy);

  const blockedProxy = new Mesh(fallbackGeometry, invisibleMaterial());
  blockedProxy.name = "blocked-proxy";
  blockedProxy.visible = false;
  scene.add(blockedProxy);

  /* Adjacency, for the neighbour emphasis on selection. */
  const neighbours = new Map<string, string[]>();
  const linkEnds = new Map<string, { a: string; b: string }>();
  for (const link of links) {
    linkEnds.set(link.id, { a: link.a, b: link.b });
    const a = neighbours.get(link.a) ?? [];
    a.push(link.b);
    neighbours.set(link.a, a);
    const b = neighbours.get(link.b) ?? [];
    b.push(link.a);
    neighbours.set(link.b, b);
  }

  let graphDisposed = false;
  const emissiveObjects: Object3D[] = [];
  for (const group of groups.values()) {
    if (group.led !== null) emissiveObjects.push(group.led);
  }
  // State rings are deliberately NOT in the bloom set. Bloom means "this element is emitting",
  // and 23 of the 26 devices here are up — a glowing green ring on nearly every node makes
  // health the loudest thing on screen, which is the exact inversion of the rule that a Critical
  // finding must outshout the furniture. The rings keep their colour and their shape; they lose
  // the halo.

  const graph: FabricGraph = {
    scene,
    groups,
    slots,
    order,
    cables,
    ground,
    pickProxy,
    pickIds,
    roleGlyphs,
    stateRings,
    hatch,
    ghostEdges,
    halo,
    hoverShell,
    selectionProxy,
    blockedProxy,
    materials,
    maps,
    tokens,
    signature: topologySignature(devices, links),
    neighbours,
    linkEnds,
    emissiveObjects,
    dispose(): void {
      // Idempotent by a flag, not by hope: BufferGeometry.dispose() fires its event every time it
      // is called, so a double dispose would re-notify every listener and, worse, hide a real
      // double-release behind "it did not throw".
      if (graphDisposed) return;
      graphDisposed = true;
      for (const group of groups.values()) {
        for (const mesh of group.meshes) {
          mesh.dispose();
          mesh.removeFromParent();
        }
        if (group.ghost !== null) {
          group.ghost.dispose();
          group.ghost.removeFromParent();
        }
        group.parts.dispose();
        group.proxyGeometry.dispose();
        for (const g of group.owned) g.dispose();
      }
      for (const mesh of [...roleGlyphs, ...stateRings]) {
        mesh.geometry.dispose();
        mesh.dispose();
        mesh.removeFromParent();
      }
      if (hatch !== null) {
        hatch.geometry.dispose();
        hatch.dispose();
        hatch.removeFromParent();
      }
      if (ghostEdges !== null) {
        ghostEdges.geometry.dispose();
        ghostEdges.material.dispose();
        ghostEdges.removeFromParent();
      }
      cables.dispose();
      ground.dispose();
      pickGeometry.dispose();
      pickMaterial.dispose();
      pickProxy.dispose();
      pickProxy.removeFromParent();
      haloGeometry.dispose();
      halo.removeFromParent();
      hoverShell.removeFromParent();
      (selectionProxy.material as Material).dispose();
      (blockedProxy.material as Material).dispose();
      selectionProxy.removeFromParent();
      blockedProxy.removeFromParent();
      materials.dispose();
      maps.dispose();
      scene.clear();
    },
  };
  return graph;
}

/**
 * A material that renders nothing at all.
 *
 * OutlineEffect builds its mask by re-rendering the selected objects with its own override
 * material, so the object has to be in the scene and `visible` — but it must not appear in the
 * beauty pass, because the real chassis is already there as an instance. Writing neither colour nor
 * depth is how one object can be present for the outline and absent from the image.
 */
function invisibleMaterial(): MeshBasicMaterial {
  const m = new MeshBasicMaterial({ colorWrite: false, depthWrite: false, depthTest: false });
  m.name = "outline-proxy";
  return m;
}

/** 1.4 px per design-brief.md §4.4: reads as an outline, survives SMAA and a 1x pixel ratio. */
function buildGhostLineMaterial(tokens: TokenPalette): LineMaterial {
  const mat = createCableMaterial("solid", 1.4, 0.95, { vertexColors: false });
  mat.color.copy(tokens.color("--claim-indeterminate"));
  return mat;
}

/* ── the scene handle ──────────────────────────────────────────────────────── */

/**
 * The handle this file actually returns.
 *
 * `contract.ts` is FROZEN and declares `stats(): SceneStats` — eight fields. `snapshot()` has
 * always returned fifteen, and the extra seven (`overBudget` among them) were therefore reachable
 * at runtime and invisible to the type system: a consumer could only get at them with a cast,
 * which is the same as not having them. A standing draw-call breach was live in the product for
 * exactly that reason — nothing could name the field that reported it.
 *
 * Widening the return type is the fix that does not require unfreezing the contract: this is a
 * SUBTYPE of `FabricScene`, so every consumer that wants the contract still gets it, and the ones
 * that need the diagnostics get them named and checked. `satisfies CreateScene` below is the proof
 * that the widening did not break conformance.
 */
export interface FabricSceneEx extends FabricScene {
  stats(): SceneStatsEx;
}

const createSceneImpl = (
  canvas: HTMLCanvasElement,
  opts: SceneOptions,
  cb: SceneCallbacks,
): FabricSceneEx => {
  const renderer = new WebGLRenderer({
    canvas,
    powerPreference: "high-performance",
    // An MSAA default framebuffer would be allocated and then thrown away the moment RenderPass
    // writes to an offscreen target: pure cost, zero benefit. SMAA in the composer does the work.
    antialias: false,
    stencil: false,
    depth: false,
  });
  renderer.outputColorSpace = SRGBColorSpace;
  // The COMPOSER owns tone mapping. Leaving it on here as well would tone-map twice.
  renderer.toneMapping = NoToneMapping;
  /* Shadow filtering, stated as a fact rather than as a wish.
   *
   * design-brief.md §4.3 asks for PCFSoftShadowMap. three 0.186.0 REMOVED it: the constant is still
   * exported for source compatibility, but WebGLShadowMap rejects it —
   *   "THREE.WebGLShadowMap: PCFSoftShadowMap has been removed. Using PCFShadowMap instead."
   * — measured in the console on every load of this app and of /fabric-preview.html. So the brief's
   * soft filter was not in force; the harder PCF was, silently, with a warning into a console
   * nobody reads. Asking for it again would not bring it back.
   *
   * PCF is therefore chosen deliberately and the softness is carried by the two mechanisms that do
   * still exist here: shadow.intensity 0.5 (lighting.ts) and the contact decals under every
   * chassis, which are what actually grounds a device at this camera distance. VSM is the only
   * remaining soft filter and it is worse for this scene specifically: under VSM every receiver
   * also casts, and this fabric's tiers sit 64 units apart, so the decks would start casting onto
   * each other — the "hard dark rectangle with no caster above it" failure, multiplied.
   *
   * DEVIATION from design-brief.md §4.3, recorded here because the brief cannot be edited from this
   * cluster: the named constant does not exist in the pinned three version. */
  renderer.shadowMap.type = INTENDED_SHADOW_MAP_TYPE;
  if (renderer.shadowMap.type !== INTENDED_SHADOW_MAP_TYPE && import.meta.env?.DEV === true) {
    // A library that substitutes our choice must fail loudly here, not warn once into a console.
    // eslint-disable-next-line no-console
    console.error(
      `fabric3d: shadow map type is ${renderer.shadowMap.type}, not the intended ` +
        `${INTENDED_SHADOW_MAP_TYPE}; the renderer substituted a different filter`,
    );
  }
  renderer.info.autoReset = false;

  const caps = probeCapabilities(renderer);
  let decision: QualityDecision =
    opts.quality === undefined
      ? chooseQuality(caps)
      : { tier: opts.quality, reasons: [`quality tier "${opts.quality}" requested by the caller`], auto: false };
  let profile = profileFor(decision.tier);
  renderer.shadowMap.enabled = profile.shadows;

  let theme = opts.theme;
  let reducedMotion = opts.reducedMotion;

  /* User-timing marks around the two costs that own the cold-load block, so the next person to ask
     "what is the 1.8-3.0 s frame?" can read the answer off a profile instead of re-deriving it.
     `performance.measure` is a few microseconds and is available in every browser this ships to. */
  const mark = <T,>(name: string, fn: () => T): T => {
    if (typeof performance === "undefined" || typeof performance.measure !== "function") return fn();
    /* determinism: both reads below feed `performance.measure` and nothing else — the profile,
       not the picture. `fn()` never sees them, so no geometry, material or animation target can
       depend on when this ran. */
    const t0 = performance.now();
    const out = fn();
    try {
      performance.measure(name, { start: t0, end: performance.now() });
    } catch {
      /* A UA that dislikes the options form is not worth failing a scene build over. */
    }
    return out;
  };

  let graph = mark("atlas:graph-build", () =>
    buildFabricGraph({
      devices: opts.devices,
      links: opts.links,
      layout: opts.layout,
      theme,
      profile,
    }),
  );

  const layoutOf = (l: LayoutResult): FabricLayout => l as FabricLayout;
  let layout = layoutOf(opts.layout);

  const backdrop = { texture: createBackdrop(graph.tokens) };
  graph.scene.background = backdrop.texture;

  /* Created by the warm-up's first stage rather than here; see the cold-load warm-up block. Null
     only before that stage runs, which is before anything has been rendered. */
  let environment: EnvironmentHandle | null = null;

  const lightingModule = createLighting(graph.tokens, profile);
  lightingModule.fit(layout.bounds);
  graph.scene.add(lightingModule.group);

  const sphere = {
    center: layout.framing.boundingSphere?.center ?? centreOf(layout),
    radius: layout.framing.boundingSphere?.radius ?? radiusOf(layout),
  };

  const cameraRig: CameraRig = createCameraRig(canvas, {
    framing: { ...layout.framing, fovDeg: layout.framing.fovDeg },
    sphere,
    box: layout.bounds,
    reducedMotion,
    width: Math.max(1, canvas.clientWidth),
    height: Math.max(1, canvas.clientHeight),
  });

  let post: PostChain = mark("atlas:post-chain", () =>
    createPostChain({
      renderer,
      scene: graph.scene,
      camera: cameraRig.camera,
      tokens: graph.tokens,
      profile,
    }),
  );

  const flow: FlowOverlay = createFlowOverlay(graph.tokens);
  graph.scene.add(flow.group);
  flow.setReducedMotion(reducedMotion);

  post.setBloomObjects([...graph.emissiveObjects, ...flow.emissiveObjects()]);

  /* ── mutable interaction state ─────────────────────────────────────────── */
  let selectedDevice: string | null = null;
  let selectedLink: string | null = null;
  let hoverDevice: string | null = null;
  let hoverLink: string | null = null;
  let highlight: HighlightState | null = null;
  let trace: Trace | null = null;
  let activeHop: number | null = null;

  let emphasis: EmphasisState = createEmphasisState(graph.order.length);
  let haloAlpha = 0;
  let haloTarget = 0;
  let hoverAlpha = 0;
  let hoverTarget = 0;

  let width = Math.max(1, canvas.clientWidth);
  let height = Math.max(1, canvas.clientHeight);
  let labelBoxes = new Float32Array(graph.order.length * 4);
  let labelKept = new Uint8Array(graph.order.length);
  let labelKey = new Float64Array(graph.order.length);
  let labelRank: number[] = graph.order.map((_, i) => i);
  let labelsShown = 0;

  let dirty = true;
  let stillFrames = 0;
  let compiled = false;
  /** Whether a compile has been REQUESTED. `compiled` means it has finished; converge waits on that. */
  let firstRendered = false;
  let overBudget = false;
  /** Consecutive rendered frames currently over the ceiling; see OVER_BUDGET_FRAMES. */
  let overBudgetFrames = 0;
  /**
   * Outline effects that currently have a non-empty selection, 0..OUTLINE_EFFECT_COUNT.
   *
   * Maintained at the two call sites that set an outline's selection rather than read back out of
   * the post chain, because the post chain is rebuilt on a quality change and the count has to
   * survive that. It is what turns the flat ceiling into the per-frame one — see
   * `drawCallBudgetFor`.
   */
  let selectionOutlineActive = false;
  let blockedOutlineActive = false;
  const activeOutlines = (): number => (selectionOutlineActive ? 1 : 0) + (blockedOutlineActive ? 1 : 0);
  /** The ceiling the last RENDERED frame was judged against, reported alongside `drawCalls`. */
  let frameDrawCallBudget = DRAW_CALL_BUDGET_BASE;
  /* NOT SEEDED WITH A PLAUSIBLE READING — acceptance E4.
   *
   * These were `lastFrameMs = 16.7` and `fpsEma = 60`, published from the first `snapshot()`
   * call onwards. Measured on the release build (review/_audit_perf_fpsema.mjs, polling
   * `window.__atlasScene.stats()` every 50 ms from navigation): at t=1218 ms the scene reported
   * `fps 60, frameMs 16.7` with ZERO draw calls, ZERO programs linked and the canvas blank —
   * and the NEXT frame took 483 ms. An absent measurement rendered as a healthy one, inside the
   * criterion that says degradation must be explicit and never silent.
   *
   * The honest state before the second frame is `not observed`: one rAF callback gives a
   * timestamp, not a duration, so there is no frame time to report until a second one arrives.
   * `framesTimed` is the denominator that says so, and it is on `SceneStatsEx` so a reader — a
   * status bar, a probe, a harness — can tell a measurement from a placeholder without knowing
   * anything about this loop. Until it is non-zero, `fps` and `frameMs` are 0 and mean nothing,
   * and `emitStats` publishes nothing at all, so the status bar reaches its own absent branch
   * ("the 3-D subsystem has not reported a frame yet") for a real reason. */
  let lastFrameMs = 0;
  let fpsEma = 0;
  /** Frames whose DURATION was measured. 0 means `fps`/`frameMs` are not a measurement. */
  let framesTimed = 0;
  /** Worst single frame in the recent window; an EMA cannot report one catastrophic frame. */
  let worstFrameMs = 0;
  let worstFrameAt = 0;
  /** Set by the visibilitychange listener: the next frame's delta spans a rAF suspension. */
  let resumedFrame = false;
  let lastStatsEmit = 0;
  let raf = 0;
  let disposed = false;

  const markDirty = (): void => {
    dirty = true;
    stillFrames = 0;
  };

  /* ── interaction ───────────────────────────────────────────────────────── */
  const interaction: Interaction = createInteraction(
    canvas,
    cameraRig.camera,
    {
      deviceProxy: graph.pickProxy,
      deviceIds: graph.pickIds,
      linkObjects: graph.cables.batches.map((b) => ({ object: b.object, segmentLinkIds: b.segmentLinkIds })),
      project(kind, id) {
        if (kind === "device") {
          const p = projectDevice(id);
          return p === null ? null : { x: p.x, y: p.y };
        }
        const ends = graph.linkEnds.get(id);
        if (ends === undefined) return null;
        const a = projectDevice(ends.a);
        const b = projectDevice(ends.b);
        if (a === null || b === null) return null;
        return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      },
    },
    {
      onHover(result: PickResult | null): void {
        api.setHover(
          result !== null && result.kind === "device" ? result.id : null,
          result !== null && result.kind === "link" ? result.id : null,
        );
        cb.onEvent({ type: "hover", result });
      },
      onPick(result: PickResult | null, modifier: boolean): void {
        cb.onEvent({ type: "pick", result, modifier });
      },
      onNeedsFrame: markDirty,
    },
  );

  /* ── projection ────────────────────────────────────────────────────────── */
  function projectDevice(id: string): { x: number; y: number; visible: boolean; distance: number } | null {
    const slot = graph.slots.get(id);
    if (slot === undefined) return null;
    _world.set(slot.centre[0], slot.top + 2.5, slot.centre[2]);
    const distance = _world.distanceTo(cameraRig.camera.position);
    _world.project(cameraRig.camera);
    const inFrustum = _world.z > -1 && _world.z < 1 && Math.abs(_world.x) <= 1.15 && Math.abs(_world.y) <= 1.15;
    return {
      // Canvas-relative CSS pixels: the DOM overlay is positioned against the canvas box, so this
      // is the coordinate space it can use without a second measurement of its own.
      x: (_world.x * 0.5 + 0.5) * width,
      y: (-_world.y * 0.5 + 0.5) * height,
      visible: inFrustum,
      distance,
    };
  }

  /**
   * Resolve which labels survive this frame. See the LABEL_* constants for why this is a collision
   * test and not a threshold. Runs once per RENDERED frame; the scene is idle the rest of the time.
   */
  function recomputeLabels(): void {
    const n = graph.order.length;
    for (let i = 0; i < n; i += 1) {
      labelKept[i] = 0;
      labelRank[i] = i;
      const s = graph.order[i];
      if (s === undefined) continue;
      const p = projectDevice(s.id);
      if (p === null || !p.visible) {
        labelBoxes[i * 4] = NaN;
        continue;
      }
      const w = s.device.host.length * LABEL_CHAR_PX + LABEL_PAD_PX;
      labelBoxes[i * 4] = p.x - w / 2;
      labelBoxes[i * 4 + 1] = p.y - LABEL_RISE_PX - LABEL_LINE_PX;
      labelBoxes[i * 4 + 2] = p.x + w / 2;
      labelBoxes[i * 4 + 3] = p.y - LABEL_RISE_PX;
      // Lower key = higher priority. The ordering is a claim about what the user is looking at, so
      // it follows the investigation state first and the topology's own hubs second.
      let key = 60;
      if (s.id === selectedDevice) key = 0;
      else if (s.id === hoverDevice) key = 1;
      else if (highlight?.blockedHost === s.id) key = 2;
      else if (trace !== null && trace.hops.some((h) => h.host === s.id)) key = 3;
      else if (highlight !== null && highlight.hosts.includes(s.id)) key = 4;
      else if (!s.device.collected) key = 20; // a device we never reached must not lose its name
      else if (layout.byId.get(s.id)?.tier === layout.diagnostics.rootTier.tier) key = 10;
      // Ties broken by screen depth, so the nearer of two overlapping nodes keeps its label.
      labelKey[i] = key * 1e6 + Math.min(999999, Math.round(p.distance));
    }

    labelRank.sort((a, b) => (labelKey[a] ?? 0) - (labelKey[b] ?? 0));

    let kept = 0;
    for (const i of labelRank) {
      if (Number.isNaN(labelBoxes[i * 4] ?? NaN)) continue;
      const x0 = labelBoxes[i * 4] ?? 0;
      const y0 = labelBoxes[i * 4 + 1] ?? 0;
      const x1 = labelBoxes[i * 4 + 2] ?? 0;
      const y1 = labelBoxes[i * 4 + 3] ?? 0;
      let clear = true;
      for (let k = 0; k < n && clear; k += 1) {
        if (labelKept[k] !== 1) continue;
        const bx0 = labelBoxes[k * 4] ?? 0;
        const by0 = labelBoxes[k * 4 + 1] ?? 0;
        const bx1 = labelBoxes[k * 4 + 2] ?? 0;
        const by1 = labelBoxes[k * 4 + 3] ?? 0;
        if (x0 < bx1 && x1 > bx0 && y0 < by1 && y1 > by0) clear = false;
      }
      if (clear) {
        labelKept[i] = 1;
        kept += 1;
      }
    }
    labelsShown = kept;
  }

  function labelAllowed(id: string): boolean {
    const slot = graph.slots.get(id);
    return slot !== undefined && labelKept[slot.index] === 1;
  }

  /* ── emphasis ──────────────────────────────────────────────────────────── */
  function recomputeEmphasis(): void {
    const focus = new Set<string>();
    const near = new Set<string>();
    if (selectedDevice !== null) {
      focus.add(selectedDevice);
      for (const n of graph.neighbours.get(selectedDevice) ?? []) near.add(n);
    }
    if (selectedLink !== null) {
      const ends = graph.linkEnds.get(selectedLink);
      if (ends !== undefined) {
        focus.add(ends.a);
        focus.add(ends.b);
      }
    }
    if (highlight !== null) {
      for (const h of highlight.hosts) focus.add(h);
      if (highlight.blockedHost !== null) focus.add(highlight.blockedHost);
      for (const l of highlight.links) {
        const ends = graph.linkEnds.get(l);
        if (ends !== undefined) {
          focus.add(ends.a);
          focus.add(ends.b);
        }
      }
    }
    if (trace !== null) {
      for (const hop of trace.hops) focus.add(hop.host);
    }

    const anyFocus = focus.size > 0;
    for (const s of graph.order) {
      const v = !anyFocus ? 0 : focus.has(s.id) ? 0 : near.has(s.id) ? RECEDE_NEIGHBOUR : RECEDE_DEPTH;
      emphasis.target[s.index] = v;
    }

    const linkRecedeTarget = new Map<string, number>();
    if (anyFocus) {
      const onPath = new Set<string>();
      if (highlight !== null) for (const l of highlight.links) onPath.add(l);
      if (highlight?.blockedLink != null) onPath.add(highlight.blockedLink);
      if (selectedLink !== null) onPath.add(selectedLink);
      // A hovered cable stays fully present even while its neighbourhood is receded. Batched
      // LineMaterials cannot widen one segment, so presence is the channel hover gets here — and
      // it is the one that actually answers "which cable is under my cursor".
      if (hoverLink !== null) onPath.add(hoverLink);
      for (const [id, ends] of graph.linkEnds) {
        // A link keeps full presence when BOTH ends are in focus: a cable with one foot in the
        // emphasised set is context, not subject, and dimming it is what keeps the subject readable
        // without ever hiding the alternative path the user needs to see.
        const both = focus.has(ends.a) && focus.has(ends.b);
        linkRecedeTarget.set(id, onPath.has(id) || both ? 0 : RECEDE_DEPTH);
      }
    }
    emphasis.linkTarget = linkRecedeTarget;
    markEmphasisDirty(emphasis);
    markDirty();
  }

  /* The easing itself lives in ./emphasis so it can be stepped by a test with a synthetic dt
     sequence — this closure needs a GPU and therefore could not be covered at all. */
  function animateEmphasis(dt: number): boolean {
    return stepEmphasis(graph, emphasis, dt);
  }

  /* ── selection / hover visuals ─────────────────────────────────────────── */
  function applySelectionVisuals(): void {
    const slot = selectedDevice === null ? undefined : graph.slots.get(selectedDevice);
    if (slot === undefined) {
      graph.selectionProxy.visible = false;
      graph.halo.visible = false;
      haloTarget = 0;
      post.setSelectionOutline([]);
      selectionOutlineActive = false;
    } else {
      graph.selectionProxy.geometry = slot.group.proxyGeometry;
      _pos.set(slot.centre[0], slot.centre[1], slot.centre[2]);
      _scale.set(1, 1, 1);
      graph.selectionProxy.matrixAutoUpdate = false;
      graph.selectionProxy.matrix.compose(_pos, _rot, _scale);
      graph.selectionProxy.visible = true;
      post.setSelectionOutline([graph.selectionProxy]);
      selectionOutlineActive = true;

      _pos.set(slot.centre[0], slot.centre[1] - chassisSpec(slot.kind).height / 2 + Y_HALO, slot.centre[2]);
      _scale.set(slot.half[0] * 5.2, 1, slot.half[2] * 5.4);
      graph.halo.matrixAutoUpdate = false;
      graph.halo.matrix.compose(_pos, _rot, _scale);
      graph.halo.visible = true;
      haloTarget = 0.09;
    }

    const blockedId = highlight?.blockedHost ?? null;
    const blocked = blockedId === null ? undefined : graph.slots.get(blockedId);
    if (blocked === undefined) {
      graph.blockedProxy.visible = false;
      post.setBlockedOutline([]);
      blockedOutlineActive = false;
    } else {
      graph.blockedProxy.geometry = blocked.group.proxyGeometry;
      _pos.set(blocked.centre[0], blocked.centre[1], blocked.centre[2]);
      _scale.set(1, 1, 1);
      graph.blockedProxy.matrixAutoUpdate = false;
      graph.blockedProxy.matrix.compose(_pos, _rot, _scale);
      graph.blockedProxy.visible = true;
      post.setBlockedOutline([graph.blockedProxy]);
      blockedOutlineActive = true;
    }
    markDirty();
  }

  function applyHoverVisuals(): void {
    const slot = hoverDevice === null ? undefined : graph.slots.get(hoverDevice);
    if (slot === undefined) {
      hoverTarget = 0;
    } else {
      graph.hoverShell.geometry = slot.group.proxyGeometry;
      _pos.set(slot.centre[0], slot.centre[1], slot.centre[2]);
      // A uniform scale would give a fat rim on the short axis; scaling by a constant WORLD
      // thickness on each axis keeps the rim visually even on a 15 x 3 x 9 box.
      const rim = 0.55;
      _scale.set(
        1 + rim / slot.half[0],
        1 + rim / Math.max(0.5, chassisSpec(slot.kind).height / 2),
        1 + rim / slot.half[2],
      );
      graph.hoverShell.matrixAutoUpdate = false;
      graph.hoverShell.matrix.compose(_pos, _rot, _scale);
      graph.hoverShell.visible = true;
      hoverTarget = 0.55;
    }
    markDirty();
  }

  function animateFades(dt: number): boolean {
    let moving = false;
    const kh = Math.min(1, dt / HOVER_MS);
    const ks = Math.min(1, dt / SELECT_MS);
    // Each fade SNAPS to its target inside the epsilon rather than stopping near it. Stopping near
    // it leaves the final opacity dependent on how many frames the easing happened to get, which
    // makes two capture runs differ by a pixel or two of alpha — and acceptance F6 asks for
    // byte-identical captures, so "close enough" is a failure.
    if (Math.abs(hoverAlpha - hoverTarget) > 0.003) {
      hoverAlpha += (hoverTarget - hoverAlpha) * kh;
      moving = true;
    } else if (hoverAlpha !== hoverTarget) {
      hoverAlpha = hoverTarget;
      moving = true;
    }
    if (moving) {
      graph.materials.hoverShell.opacity = hoverAlpha;
      graph.hoverShell.visible = hoverAlpha > 0.004;
    }
    if (Math.abs(haloAlpha - haloTarget) > 0.001) {
      haloAlpha += (haloTarget - haloAlpha) * ks;
      graph.materials.halo.opacity = haloAlpha;
      graph.halo.visible = haloAlpha > 0.002;
      moving = true;
    } else if (haloAlpha !== haloTarget) {
      haloAlpha = haloTarget;
      graph.materials.halo.opacity = haloAlpha;
      graph.halo.visible = haloAlpha > 0.002;
      moving = true;
    }
    return moving;
  }

  /* ── trace ─────────────────────────────────────────────────────────────── */
  const traceSource = {
    polylineBetween(from: string, to: string): Float32Array | null {
      for (const [id, ends] of graph.linkEnds) {
        if (ends.a === from && ends.b === to) return graph.cables.polylines.get(id) ?? null;
        if (ends.b === from && ends.a === to) {
          const poly = graph.cables.polylines.get(id);
          if (poly === undefined) return null;
          const out = new Float32Array(poly.length);
          const n = poly.length / 3;
          for (let i = 0; i < n; i += 1) {
            out[i * 3] = poly[(n - 1 - i) * 3] ?? 0;
            out[i * 3 + 1] = poly[(n - 1 - i) * 3 + 1] ?? 0;
            out[i * 3 + 2] = poly[(n - 1 - i) * 3 + 2] ?? 0;
          }
          return out;
        }
      }
      return null;
    },
    anchorOf(host: string) {
      const s = graph.slots.get(host);
      return s === undefined ? null : { x: s.centre[0], y: s.centre[1], z: s.centre[2], top: s.top };
    },
  };

  /* ── resize ────────────────────────────────────────────────────────────── */
  function applySize(w: number, h: number): void {
    width = Math.max(1, Math.round(w));
    height = Math.max(1, Math.round(h));
    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio;
    // Two separate knobs, deliberately not conflated: DPR is capped for sharpness, renderScale is
    // the adaptive-quality lever. Multiplying them is the only place they meet.
    renderer.setPixelRatio(Math.min(dpr, profile.maxPixelRatio) * profile.renderScale);
    cameraRig.setViewport(width, height);
    // composer.setSize — never renderer.setSize — resizes every pass with it. Missing a
    // LineMaterial resolution here yields cables at subtly wrong widths with no error anywhere.
    post.setSize(width, height);
    graph.cables.setResolution(width, height);
    if (graph.ghostEdges !== null) graph.ghostEdges.material.resolution.set(width, height);
    flow.setResolution(width, height);
    markDirty();
  }

  /* ── theme ─────────────────────────────────────────────────────────────── */
  function applyTheme(next: "dark" | "light"): void {
    theme = next;
    const tokens = readTokens(theme);
    graph.tokens = tokens;
    retintMaterials(graph.materials, tokens);
    graph.cables.retint(tokens);
    if (graph.ghostEdges !== null) graph.ghostEdges.material.color.copy(tokens.color("--claim-indeterminate"));
    lightingModule.retint(tokens);
    post.retint(tokens);
    flow.retint(tokens);

    for (const s of graph.order) {
      if (s.ghost) continue;
      if (s.group.body !== null) s.group.body.setColorAt(s.slot, bandTint(s.device.band, tokens, _colour));
      if (s.group.led !== null) {
        s.group.led.setColorAt(s.slot, bandEmissive(s.device.band, tokens, _colour));
      }
    }
    for (const group of graph.groups.values()) {
      for (const mesh of group.meshes) {
        if (mesh.instanceColor !== null) mesh.instanceColor.needsUpdate = true;
      }
    }
    for (const ring of graph.stateRings) {
      if (ring.instanceColor !== null) ring.instanceColor.needsUpdate = true;
    }

    backdrop.texture.dispose();
    backdrop.texture = createBackdrop(tokens);
    graph.scene.background = backdrop.texture;

    environment?.dispose();
    environment = createEnvironment(renderer, theme, profile.envSize);
    graph.scene.environment = environment.texture;
    graph.scene.environmentIntensity = environment.intensity;

    compiled = false;
    restartWarmup();
    markDirty();
  }

  /* ── quality ───────────────────────────────────────────────────────────── */
  /**
   * Apply a tier for real, including a post-chain rebuild.
   *
   * SSAO, bloom and the outlines are passes, and a composer's pass list is fixed once the passes
   * are constructed. Retuning only the knobs that happen to be live uniforms would leave a caller
   * who asked for `low` still paying for a 16-sample SSAO — a tier change that changes the label
   * and not the cost. The rebuild costs one visible hitch, which is the honest price of a rare,
   * explicitly requested change.
   */
  function applyQuality(next: QualityDecision): void {
    decision = next;
    profile = profileFor(next.tier);
    renderer.shadowMap.enabled = profile.shadows;
    lightingModule.applyProfile(profile);
    for (const group of graph.groups.values()) {
      for (const mesh of group.meshes) {
        mesh.castShadow = profile.shadows && mesh !== group.led;
        mesh.receiveShadow = profile.shadows;
      }
    }
    /* The floor is NOT restored as a receiver. geometry/ground.ts:112 sets `floor.receiveShadow =
       false` deliberately — it sits 15 units below the lowest deck and three tiers below the
       busiest one, so every shadow that reaches it is a projection from a caster the viewer cannot
       see, which is the "hard dark rectangle on empty floor" this scene spent a shadow-intensity
       budget avoiding. This line used to set it to `profile.shadows`, which meant a tier change
       turned the floor into a receiver that a freshly built scene at the SAME tier never had:
       measured `floorRecv false -> true` across one setQuality round trip, and visible as detached
       rectangles under the fabric. A tier change now changes cost, not composition. */
    graph.ground.decks.receiveShadow = profile.shadows;

    post.dispose();
    post = createPostChain({
      renderer,
      scene: graph.scene,
      camera: cameraRig.camera,
      tokens: graph.tokens,
      profile,
    });
    post.setBloomObjects([...graph.emissiveObjects, ...flow.emissiveObjects()]);
    applySelectionVisuals();
    applySize(width, height);
    slowFrames = 0;
    compiled = false;
    restartWarmup();
    overBudget = false;
    overBudgetFrames = 0;
    /* Render at least two frames, not one.
     *
     * The FIRST frame of a new post chain is not a representative frame: each OutlineEffect's
     * constructor sets `forceUpdate = true`, so both of them run a full-scene depth pass once even
     * with an empty selection — measured 124 calls / 399,816 triangles against a steady 74 /
     * 231,382 at the same tier. `renderer.info` holds the LAST RENDERED frame and an idle scene
     * stops rendering, so with a single frame that transient became the permanent readout: the HUD
     * said "124 calls" and `stats()` agreed, forever, describing a frame the scene renders once.
     * Measured after this change: a high -> low -> high round trip returns a BYTE-IDENTICAL frame
     * (sha 13aeb83e3e9356de) with 74 calls again. */
    warmupFrames = 2;
    markDirty();
  }

  /* ── cold-load warm-up ─────────────────────────────────────────────────────
   *
   * WHAT THIS REPLACED, and the measurement that chose it. The loop used to call
   * renderer.compile() and then render the composed frame inside one animation frame. Measured on
   * the release build with a real GPU (Intel iGPU, ANGLE D3D11), cold context, three runs: a single
   * animation frame of 1.99-3.26 s with 1.94-3.21 s of blocking time, during which no input was
   * serviced — a keypress requested at 600 ms did not complete until 2.4-3.8 s. The findings grid
   * was painted and looked ready for all of it.
   *
   * WHERE THE TIME ACTUALLY WENT, attributed with performance.measure rather than guessed:
   *
   *   atlas:graph-build      150-330 ms   (in the React commit, not here)
   *   atlas:environment      415-590 ms   (in the React commit, not here)
   *   renderer.compile()      20-82 ms    CHEAP
   *   first direct scene draw    175 ms   shadow programs and geometry upload included
   *   the composer's FIRST render      1650-1980 ms
   *
   * So the stall was never the compile. gl.compileShader/linkProgram return immediately under
   * KHR_parallel_shader_compile — the driver links on its own thread — and the main thread blocks
   * at the first USE of a program, which for the post chain's merged SSAO/bloom/SMAA/tone shader is
   * where 1.6-2.0 s of it lands. That is also why compileAsync measured worse when it was tried:
   * it waits on the SCENE's programs, which cost 82 ms, while the loop kept rendering frames
   * through a post chain whose programs were not ready.
   *
   * THE FIX: hand every program to the driver early, then YIELD between polls instead of blocking
   * on first use. Nothing is rendered until every program reports ready, because a frame drawn
   * through an unready program is the stall being avoided. Wall-clock time to the first painted
   * frame is roughly unchanged — the driver still needs its 1.6 s — but it is the DRIVER's thread
   * that spends it now, and the page services input throughout.
   */
  let warmupStage: WarmupStage | null = "yield";
  let envPrefilter: EnvironmentPrefilter | null = null;
  let warmupStartedAt = 0;
  let warmupTimedOut = false;
  let programsLinked = 0;
  let programsTotal = 0;
  /** How many passes of the chain have been warmed. One per frame; see advanceWarmup. */
  let warmupPass = 0;
  /** Each pass's own enabled flag, so a pass the quality profile turned off is never turned on. */
  const passEnabled: boolean[] = [];

  /**
   * Count the programs three currently holds, and how many have finished linking.
   *
   * WebGLProgram.isReady() is three's own parallel-compile predicate: it polls
   * COMPLETION_STATUS_KHR where the extension exists and reports ready immediately where it does
   * not, so a UA without the extension warms up in one frame and stalls on first use exactly as it
   * did before — no worse, and no fictitious wait.
   */
  function pollPrograms(): boolean {
    const list = renderer.info.programs;
    if (list === null || list === undefined) {
      programsTotal = 0;
      programsLinked = 0;
      return true;
    }
    programsTotal = list.length;
    programsLinked = 0;
    for (const entry of list) {
      const probe = entry as unknown as { isReady?: () => boolean };
      if (typeof probe.isReady !== "function" || probe.isReady() === true) programsLinked += 1;
    }
    return programsLinked >= programsTotal;
  }

  /**
   * Create the post chain's programs without drawing through them.
   *
   * Every Pass in postprocessing owns a Scene holding one fullscreen mesh, so the renderer's
   * ordinary compile path reaches them. renderToScreen is decided in addPass, not at render time,
   * so the material compiled here is the material the composer will use — and if that ever changes
   * upstream, the pass simply recompiles at its first render and the old stall returns for one
   * frame, rather than anything rendering wrongly.
   */
  function compilePostPrograms(): void {
    for (const pass of post.composer.passes) {
      const probe = pass as unknown as {
        scene?: Scene | null;
        camera?: Camera | null;
        enabled?: boolean;
      };
      if (probe.enabled === false) continue;
      const passScene = probe.scene;
      const passCamera = probe.camera;
      if (passScene === null || passScene === undefined) continue;
      if (passCamera === null || passCamera === undefined) continue;
      renderer.compile(passScene, passCamera);
    }
  }

  /**
   * Re-run the warm-up because new programs are about to exist: a theme change, a quality-tier
   * rebuild, or a topology change. Programs already linked report ready on the first poll, so an
   * unchanged chain costs two frames rather than a second link wait.
   */
  function restartWarmup(): void {
    warmupStage = "yield";
    envPrefilter = null;
    warmupStartedAt = 0;
    warmupPass = 0;
    passEnabled.length = 0;
  }

  /**
   * Warm ONE more pass of the chain, and report whether that was the last.
   *
   * renderer.compile() reaches a material only through object.material, so it creates neither the
   * shadow-depth programs nor NormalPass's override-material programs nor anything the composer
   * builds while rendering: measured, 23 programs exist after the compile stage and 60 after the
   * first composed frame. Those remaining 37 can only be created by rendering, and a program is
   * linked-for-real at its first USE — which is the stall.
   *
   * So the chain is rendered with a growing prefix of its passes enabled, one more per frame. Each
   * frame pays for one pass's programs and then yields, instead of one frame paying for all of
   * them. Nothing reaches the canvas until the prefix is complete, because renderToScreen belongs
   * to the last pass and the last pass is the last one enabled.
   */
  function warmupPassStep(): boolean {
    const passes = post.composer.passes;
    if (passEnabled.length !== passes.length) {
      passEnabled.length = 0;
      for (const pass of passes) passEnabled.push(pass.enabled);
    }
    for (let i = 0; i < passes.length; i += 1) {
      const pass = passes[i];
      if (pass === undefined) continue;
      pass.enabled = i <= warmupPass && passEnabled[i] === true;
    }
    mark("atlas:warmup-pass", () => post.render(0));
    for (let i = 0; i < passes.length; i += 1) {
      const pass = passes[i];
      if (pass === undefined) continue;
      pass.enabled = passEnabled[i] === true;
    }
    warmupPass += 1;
    return warmupPass >= passes.length;
  }

  /** One warm-up stage per call. Returns true when the loop may render. */
  function advanceWarmup(now: number): boolean {
    if (warmupStage === null) return true;
    if (warmupStartedAt === 0) warmupStartedAt = now;
    if (warmupStage === "yield") {
      /* Deliberately does nothing.
       *
       * The first animation frame after mount is ALREADY carrying React's commit — the render of
       * four surfaces plus the synchronous part of createScene. Measured, with the environment
       * running in that same frame: one long animation frame of 1314-1847 ms whose attribution is
       * two scripts, "MessagePort.onmessage" (React, 691-894 ms) and "FrameRequestCallback" (this
       * loop, 445-1043 ms). The browser cannot service input between a task and the rendering
       * steps of the same frame, so those two costs add up into one freeze however well each of
       * them is chunked.
       *
       * Spending this frame on nothing ends it, and the warm-up's own work starts in the next one.
       * It costs one frame of wall-clock and it is what makes the two costs two separate frames. */
      warmupStage = "environment-programs";
      return false;
    }
    if (warmupStage === "environment-programs") {
      if (environment === null) {
        envPrefilter = prepareEnvironment(renderer, theme, profile.envSize);
        const prefilter = envPrefilter;
        mark("atlas:warmup-env-programs", () => {
          /* Bound to an offscreen target for the reason prepareEnvironment documents: the canvas
             would produce the wrong program variants and every one of them would be compiled
             again inside the prefilter. */
          const previous = renderer.getRenderTarget();
          renderer.setRenderTarget(post.composer.inputBuffer);
          prefilter.prepare();
          renderer.setRenderTarget(previous);
        });
      }
      warmupStage = "environment";
      return false;
    }
    if (warmupStage === "environment") {
      /* The prefiltered environment is 0.4-1.0 s of PMREM work and it used to run inside the React
         commit that mounts the canvas, where it is unyieldable and lands on top of the graph build.
         Here it owns one frame of its own. Nothing renders before it, so no frame is ever drawn
         through a scene whose environment is missing. */
      if (environment === null) {
        /* Wait for the prefilter's programs the same way the chain's are waited for: poll, yield,
           and give up at the deadline rather than never drawing. */
        if (!pollPrograms() && now - warmupStartedAt < WARMUP_LINK_DEADLINE_MS) return false;
        const prefilter = envPrefilter;
        environment = mark("atlas:environment", () =>
          prefilter === null ? createEnvironment(renderer, theme, profile.envSize) : prefilter.generate(),
        );
        envPrefilter = null;
        graph.scene.environment = environment.texture;
        graph.scene.environmentIntensity = environment.intensity;
      }
      warmupStage = "scene-programs";
      return false;
    }
    if (warmupStage === "scene-programs") {
      /* Compiled with the composer's input buffer BOUND, which is not a detail: three's program
         cache key carries the current target's colour space and tone mapping, so programs compiled
         against the canvas are the wrong variants for a chain that renders into a HalfFloat linear
         buffer and every one of them is compiled again at first use. Measured, canvas-bound: the
         RenderPass step then cost 1451 ms of the warm-up. */
      mark("atlas:warmup-scene-programs", () => {
        const previous = renderer.getRenderTarget();
        renderer.setRenderTarget(post.composer.inputBuffer);
        renderer.compile(graph.scene, cameraRig.camera);
        renderer.setRenderTarget(previous);
      });
      warmupStage = "post-programs";
      return false;
    }
    if (warmupStage === "post-programs") {
      mark("atlas:warmup-post-programs", compilePostPrograms);
      warmupStage = "linking";
      return false;
    }
    if (warmupStage === "linking") {
      if (pollPrograms()) {
        warmupStage = "passes";
        return false;
      }
      if (now - warmupStartedAt >= WARMUP_LINK_DEADLINE_MS) {
        warmupTimedOut = true;
        warmupStage = "passes";
        return false;
      }
      return false;
    }
    if (warmupPassStep()) {
      warmupStage = null;
      return true;
    }
    if (now - warmupStartedAt >= WARMUP_LINK_DEADLINE_MS) {
      warmupTimedOut = true;
      warmupStage = null;
      return true;
    }
    return false;
  }

  /* ── render loop ───────────────────────────────────────────────────────── */
  /** Frames still owed after a post-chain rebuild, so the published reading is a steady frame. */
  let warmupFrames = 0;
  let lastNow = 0;
  let slowFrames = 0;

  /**
   * The render loop.
   *
   * determinism: `now` is a clock — `requestAnimationFrame` hands this callback the same
   * DOMHighResTimeStamp `performance.now()` returns, which is why the determinism gate counts it
   * as a clock READ even though nothing here calls one. Everything derived from it (`fpsEma`,
   * `lastFrameMs`, `worstFrameMs`) is telemetry, and telemetry reaches the DOM in exactly one
   * place: the renderer disclosure in `app/StatusBar.tsx`, behind a click that no default view and
   * no capture state performs. It steers NOTHING that is drawn — the quality tier is chosen from
   * the median of the first 60 frames and then latched, and `dt` advances animators that the
   * capture harness waits out via `converged`. This note is what acceptance F6 rests on, so if a
   * frame-timing value ever starts deciding geometry, colour or layout, it stops being true.
   */
  function frame(now: number): void {
    if (disposed) return;
    raf = requestAnimationFrame(frame);

    /* TWO numbers, deliberately, because they answer two different questions.
     *
     * `raw` is how long the frame ACTUALLY took. `dt` is how far the simulation is allowed to be
     * advanced by it. They used to be one clamped value, and that made the telemetry incapable of
     * expressing a bad frame: `lastFrameMs = Math.min(64, …)` saturated at 64, and the fps figure
     * derived from it bottomed out at 15.6 — then the slow EMA pulled it back into the mid-50s,
     * just above the 55 fps acceptance bar, whatever had happened. Measured 2026-09-21 by
     * injecting synchronous work into one frame on a real GPU: a true 800.0 ms frame (1.3 fps) was
     * published as `frameMs 64, fps 55.3, tier high`. That is degradation reported as health, in
     * the exact signal the frame-rate criterion cites as its evidence.
     *
     * The clamp is still right for the SIMULATION: a 3 s gap (a backgrounded tab, a breakpoint)
     * must not teleport an animation across three seconds of its curve. So the clamp stays on
     * `dt`, which is what feeds the animators and the post chain, and `raw` is what is reported.
     *
     * And the FIRST callback has neither number: it carries a timestamp with nothing to
     * subtract it from. `first` marks it, so the 16.7 below advances the simulation by a
     * nominal frame (which it must — the animators need a dt) without being reported as a
     * measured one. Reporting it was how a blank canvas came to say 60 fps. */
    const first = lastNow === 0;
    const raw = first ? 16.7 : now - lastNow;
    const dt = Math.min(64, raw);
    lastNow = now;

    /* A frame delta measured across a rAF suspension is not a slow frame — the browser stopped
       calling us. That is the one case where `raw` would lie in the OTHER direction, so it is
       excluded explicitly and narrowly: only the single frame that follows a visibility change,
       and only because a visibilitychange listener fired. Nothing else is ever suppressed. */
    const suspended = resumedFrame;
    resumedFrame = false;

    if (!suspended && !first) {
      /* Measured for EVERY frame, before the idle short-circuit below. A frame in which the scene
         had nothing to redraw but the main thread was blocked for 800 ms is still 800 ms the user
         waited, and reporting only rendered frames would hide exactly that. */
      lastFrameMs = raw;
      framesTimed += 1;
      /* SEEDED from the first real sample rather than decayed towards it from a starting value.
         A 0.9 EMA started at a constant takes ~20 frames to forget it, which is what made the
         readout lag a stall as well as precede one. */
      const instant = 1000 / Math.max(1, raw);
      fpsEma = framesTimed === 1 ? instant : fpsEma * 0.9 + instant * 0.1;
      /* The worst single frame in the last WORST_FRAME_WINDOW_MS. An EMA averages one catastrophic
         frame out of existence within a few frames; a windowed maximum cannot.
         A SLIDING window rather than "since the last emit": tying it to the emit made the value
         race the 500 ms emitter, so a probe that burned a frame and then read `stats()` got the
         real number or 16.8 depending on which side of an emit it landed — measured, twice out of
         three injections. A bad frame is now visible to ANY reader for a full second after it
         happened, whoever asks and however they ask. */
      if (raw >= worstFrameMs || now - worstFrameAt > WORST_FRAME_WINDOW_MS) {
        worstFrameMs = raw;
        worstFrameAt = now;
      }
    }

    /* There is deliberately NO `if (document.hidden) return` here.
     *
     * A hidden tab already costs nothing: the browser suspends requestAnimationFrame, which is the
     * specified mechanism and the one that actually saves the battery. An explicit hidden-check
     * adds nothing on top of it and breaks the contexts that matter most — a headless capture and
     * an embedded preview pane both report `document.visibilityState === "hidden"` while still
     * driving rAF and still needing frames. Measured: the preview pane renders with hidden = true,
     * and the guard turned the whole fabric into an empty canvas with no error anywhere. Idleness
     * is handled by the dirty flag below, which is a statement about the SCENE rather than a guess
     * about the window. */
    interaction.flushHover();

    let moved = cameraRig.update(now);
    moved = animateEmphasis(dt) || moved;
    moved = animateFades(dt) || moved;
    moved = flow.update(now, cameraRig.camera) || moved;

    if (moved) markDirty();
    // See applyQuality: the first frame of a new post chain is atypical, so it is never the last
    // one rendered. Costs at most two frames, and only after an explicit tier change.
    if (warmupFrames > 0) {
      warmupFrames -= 1;
      markDirty();
    }

    if (!dirty) {
      stillFrames += 1;
      emitStats(now);
      return;
    }

    /* The warm-up owns every frame before the first painted one; the block above it carries the
       measurement that shaped it. Each stage returns to the event loop, so a keystroke during the
       cold load is serviced between two stages instead of after all of them. */
    if (!compiled) {
      if (!advanceWarmup(now)) {
        markDirty();
        emitStats(now);
        return;
      }
      compiled = true;
    }

    recomputeLabels();

    /* The camera rig re-fits near/far to the fabric whenever the view moves far enough
       (camera.ts), and one pass in the chain caches that pair. Nothing else in the frame reads it,
       so the sync lives here, next to the render it has to be true for — and it is a no-op unless
       the projection actually moved. See `postfx.ts :: syncCamera`. */
    post.syncCamera();

    renderer.info.reset();
    if (!firstRendered) {
      firstRendered = true;
      mark("atlas:first-render", () => post.render(dt / 1000));
    } else {
      post.render(dt / 1000);
    }

    /* A rebuild frame costs about 50 extra calls once (see DRAW_CALL_BUDGET); a REGRESSION costs
       them every frame. Two consecutive breaching rendered frames separates the two without
       hiding either — the dev console names every breaching frame, standing or not.

       The ceiling is the one that applies to THIS frame: the base budget plus a surcharge for each
       outline effect currently selecting something. A flat ceiling could only be right for one of
       those frames, and it was set for the idle one, which is why a traced frame breached it
       permanently and nobody could see it. */
    frameDrawCallBudget = drawCallBudgetFor(activeOutlines());
    if (renderer.info.render.calls > frameDrawCallBudget) {
      overBudgetFrames += 1;
      if (import.meta.env?.DEV === true) {
        // eslint-disable-next-line no-console
        console.error(
          `fabric3d: ${renderer.info.render.calls} draw calls exceeds the budget of ` +
            `${frameDrawCallBudget} for a frame with ${activeOutlines()} outline effect(s) active ` +
            `(consecutive breaching frames: ${overBudgetFrames})`,
        );
      }
      if (overBudgetFrames >= OVER_BUDGET_FRAMES) overBudget = true;
    } else {
      overBudgetFrames = 0;
      overBudget = false;
    }

    /* Adaptive step-down. Counted over RENDERED frames only: idle frames cost nothing and would
       otherwise dilute the average into never tripping. The step is announced, not silent. */
    if (decision.auto && decision.tier !== "low") {
      // Judged on the TRUE delta, and announced with it: a clamped 64 in this sentence would tell
      // the reader the step-down happened over a 64 ms frame when it happened over an 800 ms one.
      if (!suspended && raw > SLOW_FRAME_MS) slowFrames += 1;
      else if (!suspended) slowFrames = Math.max(0, slowFrames - 1);
      if (slowFrames >= SLOW_FRAMES_BEFORE_STEP) {
        const next: QualityTier = decision.tier === "high" ? "balanced" : "low";
        const measured = Math.round(raw);
        applyQuality({
          tier: next,
          reasons: [
            ...decision.reasons,
            `stepped down to ${next}: ${SLOW_FRAMES_BEFORE_STEP} rendered frames over ` +
              `${SLOW_FRAME_MS} ms (last ${measured} ms) on this machine`,
          ],
          auto: true,
        });
        return;
      }
    }

    dirty = false;
    stillFrames = 0;
    emitStats(now);
  }

  function converged(): boolean {
    // "Converged" here means: nothing is animating, the camera is at rest, the last state change
    // has been rendered, and at least two still frames have followed it. There is no temporal
    // accumulation in this chain, and every easing SNAPS to its target and flushes the snap
    // (./emphasis), so a settled frame IS the final frame — which is exactly what the capture
    // harness needs to know before it takes a picture.
    //
    // The rule is `isConverged` in ./emphasis rather than four inline booleans, because this is the
    // one predicate the whole capture protocol waits on and a predicate inside a closure that
    // requires a GPU cannot be executed by a test.
    return isConverged({
      compiled,
      dirty,
      stillFrames,
      cameraTweening: cameraRig.isTweening(),
    });
  }

  function snapshot(): SceneStatsEx {
    return {
      /* 0 while `framesTimed` is 0, and it does not mean "0 frames per second" — it means no
         frame has been timed yet. `framesTimed` is the field that says which. */
      fps: Math.round(fpsEma * 10) / 10,
      frameMs: Math.round(lastFrameMs * 100) / 100,
      worstFrameMs: Math.round(worstFrameMs * 100) / 100,
      drawCalls: renderer.info.render.calls,
      triangles: renderer.info.render.triangles,
      programs: renderer.info.programs?.length ?? 0,
      quality: decision.tier,
      converged: converged(),
      qualityReasons: decision.reasons,
      qualityAuto: decision.auto,
      overBudget,
      drawCallBudget: frameDrawCallBudget,
      activeOutlines: activeOutlines(),
      missingTokens: graph.tokens.missing,
      undrawnHops: flow.undrawnHops(),
      labelsShown,
      labelsTotal: graph.order.length,
      warmupStage,
      programsLinked,
      programsTotal,
      warmupTimedOut,
      framesTimed,
    };
  }

  function emitStats(now: number): void {
    /* A reading with no measured frame in it is not a reading. Publishing one is what put
       "fabric 60 fps" in the status bar over a blank stage; withholding it leaves the bar on its
       own honest branch instead. `stats()` still answers — a probe asking directly gets the
       counters AND `framesTimed: 0` to interpret them with. */
    if (framesTimed === 0) return;
    if (now - lastStatsEmit < 500) return;
    lastStatsEmit = now;
    cb.onEvent({ type: "stats", stats: snapshot() });
  }

  const onVisibility = (): void => {
    // rAF is suspended while hidden. Mark the next delta so it is not published as a slow frame.
    resumedFrame = true;
    markDirty();
  };
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibility);
  }

  const onCameraChange = (): void => {
    markDirty();
  };
  const onCameraEnd = (): void => cb.onEvent({ type: "camera", settled: true });
  cameraRig.controls.addEventListener("change", onCameraChange);
  cameraRig.controls.addEventListener("end", onCameraEnd);

  applySize(canvas.clientWidth || 1, canvas.clientHeight || 1);
  recomputeEmphasis();
  raf = requestAnimationFrame(frame);

  const bandViolations = checkAuthoringBands(graph.materials.all());
  if (bandViolations.length > 0 && import.meta.env?.DEV === true) {
    // eslint-disable-next-line no-console
    console.error("fabric3d: material authoring band violations", bandViolations);
  }

  const api: FabricSceneEx = {
    setData(devices: Device[], links: Link[], nextLayout: LayoutResult): void {
      const signature = topologySignature(devices, links);
      if (signature === graph.signature) {
        // Same topology: the GPU buffers are still correct and only the per-instance colours can
        // have moved. Rebuilding here would drop every material and recompile every shader for a
        // band change, which is the kind of thing that turns a filter into a stutter.
        for (const s of graph.order) {
          const next = devices.find((d) => d.id === s.id);
          if (next === undefined) continue;
          s.device = next;
          if (!s.ghost && s.group.body !== null) {
            s.group.body.setColorAt(s.slot, bandTint(next.band, graph.tokens, _colour));
          }
          if (!s.ghost && s.group.led !== null) {
            s.group.led.setColorAt(s.slot, bandEmissive(next.band, graph.tokens, _colour));
          }
        }
        for (const group of graph.groups.values()) {
          for (const mesh of group.meshes) {
            if (mesh.instanceColor !== null) mesh.instanceColor.needsUpdate = true;
          }
        }
        markDirty();
        return;
      }

      const previous = graph;
      graph.scene.remove(flow.group);
      lightingModule.group.removeFromParent();
      graph = buildFabricGraph({ devices, links, layout: nextLayout, theme, profile });
      layout = layoutOf(nextLayout);
      graph.scene.background = backdrop.texture;
      if (environment !== null) {
        graph.scene.environment = environment.texture;
        graph.scene.environmentIntensity = environment.intensity;
      }
      graph.scene.add(lightingModule.group);
      graph.scene.add(flow.group);
      lightingModule.fit(layout.bounds);
      previous.dispose();

      emphasis = createEmphasisState(graph.order.length);
      labelBoxes = new Float32Array(graph.order.length * 4);
      labelKept = new Uint8Array(graph.order.length);
      labelKey = new Float64Array(graph.order.length);
      labelRank = graph.order.map((_, i) => i);
      markEmphasisDirty(emphasis);
      cameraRig.setHomeFraming(
        layout.framing,
        {
          center: layout.framing.boundingSphere?.center ?? centreOf(layout),
          radius: layout.framing.boundingSphere?.radius ?? radiusOf(layout),
        },
        layout.bounds,
      );
      post.setBloomObjects([...graph.emissiveObjects, ...flow.emissiveObjects()]);
      applySize(width, height);
      recomputeEmphasis();
      applySelectionVisuals();
      compiled = false;
      restartWarmup();
      markDirty();
    },

    setSelection(deviceId: string | null, linkId: string | null): void {
      if (deviceId === selectedDevice && linkId === selectedLink) return;
      selectedDevice = deviceId;
      selectedLink = linkId;
      applySelectionVisuals();
      recomputeEmphasis();
      markEmphasisDirty(emphasis);
    },

    setHover(deviceId: string | null, linkId: string | null): void {
      if (deviceId === hoverDevice && linkId === hoverLink) return;
      hoverDevice = deviceId;
      const linkChanged = linkId !== hoverLink;
      hoverLink = linkId;
      if (linkChanged) {
        recomputeEmphasis();
        markEmphasisDirty(emphasis);
      }
      // Hover is the weak state: it changes a rim and a cursor and nothing else. It must never
      // move the camera and never re-run the layout (contract.ts says so; this is where it holds).
      applyHoverVisuals();
    },

    setHighlight(h: HighlightState | null): void {
      highlight = h;
      applySelectionVisuals();
      recomputeEmphasis();
      markEmphasisDirty(emphasis);
    },

    setTrace(next: Trace | null, hop: number | null): void {
      trace = next;
      activeHop = hop;
      flow.setTrace(next, activeHop, traceSource);
      post.setBloomObjects([...graph.emissiveObjects, ...flow.emissiveObjects()]);
      recomputeEmphasis();
      markEmphasisDirty(emphasis);
      const s = flow.pathSphere();
      if (s !== null) {
        _world.set(s.center[0], s.center[1], s.center[2]);
        cameraRig.moveTo(
          frameSphereFromCurrentView(cameraRig.camera, cameraRig.controls.target, _world, s.radius, 1.35),
        );
      }
      markDirty();
    },

    focusDevice(deviceId: string | null, focusOpts?: { immediate?: boolean }): void {
      if (deviceId === null) {
        cameraRig.home(focusOpts);
        markDirty();
        return;
      }
      const framing = focusFramingFor(deviceId);
      if (framing === null) return;
      cameraRig.moveTo(framing, focusOpts);
      markDirty();
    },

    resetCamera(resetOpts?: { immediate?: boolean }): void {
      cameraRig.home(resetOpts);
      markDirty();
    },

    setTheme(next: "dark" | "light"): void {
      if (next === theme) return;
      applyTheme(next);
    },

    setQuality(q: QualityTier): void {
      if (q === decision.tier) return;
      applyQuality({ tier: q, reasons: [`quality tier "${q}" set by the caller`], auto: false });
    },

    resize(w: number, h: number): void {
      applySize(w, h);
    },

    pick(clientX: number, clientY: number): PickResult | null {
      return interaction.pick(clientX, clientY);
    },

    project(deviceId: string): { x: number; y: number; visible: boolean } | null {
      const p = projectDevice(deviceId);
      if (p === null) return null;
      return { x: p.x, y: p.y, visible: p.visible && labelAllowed(deviceId) };
    },

    stats(): SceneStatsEx {
      return snapshot();
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(raf);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
      cameraRig.controls.removeEventListener("change", onCameraChange);
      cameraRig.controls.removeEventListener("end", onCameraEnd);
      interaction.dispose();
      flow.dispose();
      post.dispose();
      lightingModule.dispose();
      environment?.dispose();
      backdrop.texture.dispose();
      graph.dispose();
      cameraRig.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };

  function focusFramingFor(deviceId: string): { position: [number, number, number]; target: [number, number, number] } | null {
    const slot = graph.slots.get(deviceId);
    if (slot === undefined) return null;
    const ids = [deviceId, ...(graph.neighbours.get(deviceId) ?? [])];
    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    for (const id of ids) {
      const s = graph.slots.get(id);
      if (s === undefined) continue;
      minX = Math.min(minX, s.centre[0] - s.half[0]);
      maxX = Math.max(maxX, s.centre[0] + s.half[0]);
      minY = Math.min(minY, s.centre[1] - s.half[1]);
      maxY = Math.max(maxY, s.centre[1] + s.half[1]);
      minZ = Math.min(minZ, s.centre[2] - s.half[2]);
      maxZ = Math.max(maxZ, s.centre[2] + s.half[2]);
    }
    const own = Math.hypot(slot.half[0], slot.half[1], slot.half[2]);
    const neighbourhood = Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2;
    // Clamped to a band around the device's OWN size. A hub here has seventeen neighbours, and
    // framing all of them is framing the whole fabric — which answers a different question from
    // the one "focus this device" asks. The cap keeps the subject unmistakably the subject while
    // still pulling back far enough to show which neighbourhood it sits in.
    const radius = Math.min(Math.max(neighbourhood, own * 1.9), own * 4.6);
    // Centred on the DEVICE, not on the neighbourhood's midpoint: with the radius capped above,
    // a midpoint far from a hub would frame a region the hub is not even in.
    _world.set(slot.centre[0], slot.centre[1], slot.centre[2]);
    // Keeps the CURRENT view direction. Re-aiming without re-orienting is what lets a user follow
    // a selection instead of having to re-find where they were.
    return frameSphereFromCurrentView(cameraRig.camera, cameraRig.controls.target, _world, radius, 1.4);
  }

  return api;
};

/**
 * The exported entry point.
 *
 * `satisfies` rather than a type annotation: the annotation would ERASE the widened `stats()`
 * return type back to the contract's, which is the exact loss this file just undid. This keeps
 * `FabricSceneEx` visible to callers AND proves the implementation still conforms to `CreateScene`:
 * if the contract gains a method, this line stops compiling.
 */
export const createScene = createSceneImpl satisfies CreateScene;

function centreOf(layout: FabricLayout): [number, number, number] {
  return [
    (layout.bounds.min[0] + layout.bounds.max[0]) / 2,
    (layout.bounds.min[1] + layout.bounds.max[1]) / 2,
    (layout.bounds.min[2] + layout.bounds.max[2]) / 2,
  ];
}

function radiusOf(layout: FabricLayout): number {
  return (
    Math.hypot(
      layout.bounds.max[0] - layout.bounds.min[0],
      layout.bounds.max[1] - layout.bounds.min[1],
      layout.bounds.max[2] - layout.bounds.min[2],
    ) / 2
  );
}

export default createScene;
