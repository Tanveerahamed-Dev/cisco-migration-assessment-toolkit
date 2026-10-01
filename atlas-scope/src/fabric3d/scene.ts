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
  BackSide,
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
  type WebGLRenderTarget,
} from "three";
import type { Camera } from "three";
import type { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import { presentBand } from "../core/band-qualification";
import type { Device, Link, Trace } from "../core/types";
import { roleGlyphClass } from "../core/roles";
import {
  CAMERA_TWEEN_MS,
  createCameraRig,
  frameSphereFromCurrentView,
  measureDrawnBounds,
  type CameraRig,
} from "./camera";
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
  HOVER_EASE,
  LABEL_DROP_EVERY_FRAMES,
  RECEDE_DEPTH,
  RECEDE_NEIGHBOUR,
  SELECT_EASE,
  createEaseChannel,
  createEmphasisState,
  createTierFadeSlot,
  tierFadeCopy,
  stepEaseChannel,
  isConverged,
  markEmphasisDirty,
  stepEmphasis,
  type TierFadeCopy,
  type EmphasisState,
  type RecedeMirror,
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
  ROLE_GLYPHS,
  buildStateRing,
  chassisSilhouette,
  chassisSpec,
  normaliseKind,
  unitDecal,
  unitDiscDecal,
  type ChassisKind,
  type ChassisParts,
  type StateRingShape,
} from "./geometry/chassis";
import { buildCables, coverageGamma, createCableMaterial, MIN_STROKE_PX, setCoverageGamma, type CableSet } from "./geometry/cables";
import { DECK_DROP, Y_HALO, Y_STATE_RING, buildGround, type GroundSet } from "./geometry/ground";
import { createInteraction, PICK_LAYER, type Interaction } from "./interaction";
import { resolveLabels } from "./labelResolve";
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
import { createPostChain, nextHistoryWeight, type PostChain } from "./postfx";
import { createPanelInputGate, isFabricTarget } from "./panelInput";
import {
  createForeignWorkLedger,
  createFrameRateBar,
  createGestureGate,
  createPresentationCadence,
  createStepDownJudge,
  createStepUpPolicy,
  createTierFadeHold,
  TIER_FADE_HOLD_DEFAULTS,
  displayLimitReason,
  effectiveBars,
  frameIsFabricEvidence,
  STEP_DOWN_DEFAULTS,
} from "./stepdown";
import {
  chooseQuality,
  effectivePixelRatio,
  probeCapabilities,
  pinQuality,
  probeReasonsAt,
  profileFor,
  SHADOW_MAP_IN_USE,
  SHADOW_MAP_REASON,
  tierIsAdaptive,
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

/**
 * A composed frame with no outline effect active. Measured 74 at `high` on the 9cc348bd reference sample
 * (2026-09-21, the compiled fabric of the commit that recorded it); 14 calls of headroom. A measurement of ONE
 * 26-device sample, not a derived bound: device meshes are instanced per chassis kind and per glyph/ring class, so
 * the count scales with the number of distinct kinds and classes present, not with the device count, but no
 * larger fleet had been measured when this was set.
 *
 * RE-MEASURED 2026-09-28 (phase 3), after the "other" role glyph added a fourth role-glyph instanced mesh, on the
 * regenerated reference sample (GOLDEN_SHA, src/test-support/golden-sample.ts) (Playwright Chromium, SwiftShader WebGL2, 1440x900, no outline active,
 * `stats().drawCalls` after the warm-up converged): 71 at `high`, 31 at `low`. The sample has no role outside
 * access/distribution, so its "other" mesh has count 0 and three.js skips it (WebGLBufferRenderer:
 * `if ( primcount === 0 ) return;`). With a third of the sample's roles re-stated as "core" through `setData`:
 * 73 at `high` (+2: the glyph mesh is drawn in two passes) and 32 at `low` (+1). Every figure is inside this base.
 */
export const DRAW_CALL_BUDGET_BASE = 88;

/**
 * What one `OutlineEffect` with a non-empty selection is allowed to add.
 *
 * Measured +29 (selection outline) and +38 (blocked outline, which also runs a Kawase blur), on the same
 * 9cc348bd reference sample as the base. The
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
 * How long the camera must hold still before the ambient-occlusion stage is restored (see
 * `PostChain.setMotion`). Long enough that a drag's momentary pauses do not flicker occlusion on and
 * off; short enough that the settled frame arrives before a reader can study it.
 */
const MOTION_HOLD_MS = 140;

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
 * decision is announced in `stats().qualityReasons` rather than made quietly. It used to only
 * ever step DOWN, on the argument that a step back up would oscillate; the measured cost of that
 * ratchet was a whole session stuck on `low` after one heavy gesture. It now also steps back UP,
 * only while idle and with a strike count that makes a failed retry permanent — bounded, announced
 * recovery rather than oscillation (./stepdown `createStepUpPolicy`).
 */
/* The rule itself (a windowed fraction of rendered frames over budget, or a window fps below the
   bar) lives in ./stepdown, where a test steps it. The +1/-1 counter it replaced could not see a
   bimodal frame series and let a sustained 29-39 fps run stay on `high`, unannounced. */

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

/* Every eased fade's duration and curve — recession, the hover rim (HOVER_MS) and the selection
   halo (SELECT_MS) — lives in ./emphasis, the ease owner, alongside the machine that steps them. It
   was extracted so it can be stepped by a test without a GPU, and it is the only place a per-frame
   ease may be written (src/core/motion-inventory.test.ts parses src/ for any other). */
/**
 * The hover rim: its width in CSS PIXELS at the chassis, and the shell's opacity.
 *
 * Was 0.55 world units at 0.55 opacity, and MEASURED too weak to be a state (A5 critic,
 * 2026-09-22): hovering access13 changed 515 of 1,115,920 canvas pixels, mean delta 0.033/255 — a
 * ~2 px hairline a reader does not notice. Then 1.3 world units, which read at the default framing
 * but, being a WORLD width, grew with the dolly: with the dolly floor now reaching a single chassis
 * (camera.ts SUBJECT_FILL) a world-width rim became a ~40 px slab round it. Every rim is therefore
 * specified in screen pixels (design-brief §4.7 does the same) and converted to a world width at
 * the chassis's own distance on every rendered frame (`refreshRims`). Horizontal-only, see
 * applyHoverVisuals.
 */
export const HOVER_RIM_PX = 2.5;
export const HOVER_RIM_OPACITY = 0.85;
/**
 * The selection rim, drawn as geometry at EVERY tier (design-brief §4.7: "2.5 px --accent rim").
 *
 * It used to be only the OutlineEffect, which the low tier does not run (quality.ts
 * `outline: false`) — and the low tier is what the capability probe picks on any software
 * rasteriser. MEASURED (C5 audit, 2026-09-22, SwiftShader auto-low and GPU forced low): a selected
 * access12 got no rim at all, only a faint halo and the dimming of everything else, while
 * `stats().activeOutlines` still said 1. Now the same silhouette-rim technique as the hover and the
 * blocked alarm (see `makeRimShell`), so selection reads the same at every tier and a tier change
 * changes cost, not composition. Wider than the hover rim, which stays the weak state.
 */
export const SELECT_RIM_PX = 3.5;
/* Rim shells draw after every translucent surface of the fabric (ghost chassis 3, hatch and ghost
   edges 4, the flow's path and blocked glyph 4-5), so the depth-only occluder in front of each one
   cannot hide any of them. */
const RIM_OCCLUDER_ORDER = 10;
const RIM_SHELL_ORDER = 11;
/** The selection halo's opacity (design-brief §4.7: `--accent` @ 9 %). */
const SELECT_HALO_ALPHA = 0.09;

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
/** The blocked host's alarm rim, CSS px per horizontal side at the chassis (see HOVER_RIM_PX). */
const BLOCKED_RIM_PX = 3.5;
/** How far a chassis screen box is inset before a label over it counts as covering it, px. */
const LABEL_OCCLUDER_INSET_PX = 3;

/**
 * Hysteresis for the collision resolver, in CSS pixels — the collision-space equivalent of the
 * 0.06 dolly hysteresis design-brief.md §4.9 item 11 specifies for the threshold rule this
 * resolver replaced. The replacement dropped the term, and MEASURED (render audit #7): sampling
 * `labelsShown` every frame through an eight-target focus tour gave 9 direction reversals and 2
 * single-frame blips (…20,20,21,21,21,20,21,21,21,22…) — a name removed and restored inside three
 * frames, exactly while the camera moves and the reader is watching.
 *
 * A label shown last frame is tested with its box SHRUNK by this margin (it must overlap by more
 * than the margin before it goes); a hidden one is tested with its box GROWN by it (it must clear
 * by the margin before it comes back). Between the two, the previous verdict stands.
 */
const LABEL_HYSTERESIS_PX = 5;


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
   * Labels the resolver withheld because they would have been drawn over a chassis NEARER to the
   * camera than the device they name. DOM labels have no depth, so without this rule a far-row
   * name floats in front of the hardware that should hide it (C5 audit). Published so a close view
   * that shows fewer names says why.
   */
  labelsBehindChassis?: number;
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
  /**
   * True while the last judgeable window of RENDERED frames ran below acceptance E4's 55 fps bar.
   *
   * Independent of the tier: the step-down rule deliberately tolerates the 45-55 fps band, and
   * before this field that band was reported as `high` with nothing else said — degradation
   * reported as health. It changes nothing about rendering; it only makes the shortfall explicit
   * (see `createFrameRateBar` in ./stepdown). Lowered on a tier change, because the new tier has
   * not been measured yet.
   */
  frameRateBelowBar: boolean;
  /**
   * The history weight the last presented frame used (postfx.ts HISTORY_AA) and the camera step that
   * decided it, in drawing-buffer px. 0 = that frame was the plain chain's output, which every
   * settled frame is. Reported so a motion capture can say which frames were blended.
   */
  historyWeight?: number;
  historyCameraStepPx?: number | null;
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

/** The two properties of a post-chain pass the pass-by-pass warm-up reads and writes. */
export interface WarmupPassLike {
  enabled: boolean;
  readonly renderToScreen: boolean;
}

/**
 * One frame of the "passes" warm-up stage: render the chain with passes `0..step` enabled (each
 * still subject to its own profile flag), then restore every flag. Returns whether this was the
 * last step.
 *
 * WHY EVERY STEP THAT DOES NOT PRESENT DRAWS THE INTERACTION VISUALS (acceptance E3, 2026-09-23).
 * Compiling a program is not the whole of its first-use cost. MEASURED on the release build
 * (Intel iGPU, ANGLE D3D11, fresh browser per trial, WebGL entry points wrapped): the FIRST device
 * selection after load linked NO program — every one of them was created and polled ready by the
 * compile stages above — yet the scene frame that first drew the selection spent 105 ms inside
 * `getProgramInfoLog` for `outline-proxy`, then 1.7 / 1.7 / 0.4 / 4 ms for `selection-halo`,
 * `rim-occluder`, `hover-shell` and the outline's `DepthComparisonMaterial`, in a 135-144 ms
 * FrameRequestCallback on the click's path (core2 ON-PATH in 15 of 15 fresh-browser trials in the
 * acceptance audit). That call is a synchronous round trip to the GPU process, so it waits for
 * everything queued before it, and what was queued was the FIRST DRAW through those programs:
 * the backend builds its per-draw executables (input layout, output signature) lazily, at draw.
 * `renderer.compile` and the recorder in `discoverPostPrograms` both stop short of a draw.
 *
 * So the warm-up now DRAWS through them: every step whose enabled prefix does not reach the screen
 * renders into the chain's own buffers with the interaction visuals primed (visible, and in their
 * outline selections), which pays those first draws here, in warm-up frames that already yield
 * between steps and while the stage still says it is building. The step that reaches the screen
 * is never primed, so no primed pixel is ever presented; its render also clears the outline masks
 * the primed steps left (an outline effect re-runs once after its selection empties).
 */
export function runWarmupPassStep(
  passes: readonly (WarmupPassLike | undefined)[],
  enabledByProfile: readonly boolean[],
  step: number,
  render: () => void,
  primeInteractionVisuals: (draw: () => void) => void,
): boolean {
  let presents = false;
  for (let i = 0; i < passes.length; i += 1) {
    const pass = passes[i];
    if (pass === undefined) continue;
    pass.enabled = i <= step && enabledByProfile[i] === true;
    if (pass.enabled && pass.renderToScreen) presents = true;
  }
  try {
    if (presents) render();
    else primeInteractionVisuals(render);
  } finally {
    for (let i = 0; i < passes.length; i += 1) {
      const pass = passes[i];
      if (pass === undefined) continue;
      pass.enabled = enabledByProfile[i] === true;
    }
  }
  return step + 1 >= passes.length;
}

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
  /** Per-device meshes outside the chassis groups that recede with their device (emphasis.ts). */
  mirrors: RecedeMirror[];
  /** The uncollected hatch on rectangular lids. */
  hatch: InstancedMesh | null;
  /** The same hatch as a DISC, for the round access-point lid (see buildFabricGraph). */
  hatchRound: InstancedMesh | null;
  ghostEdges: LineSegments2 | null;
  halo: Mesh;
  hoverShell: Mesh;
  /** The selection rim; drawn at EVERY tier (see SELECT_RIM_PX). */
  selectionShell: Mesh;
  /** The blocked host's alarm rim; drawn at EVERY tier (see buildFabricGraph). */
  blockedShell: Mesh;
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

const RING_SHAPES: readonly StateRingShape[] = ["solid", "dashed", "double"];

/**
 * What `setData` compares to decide between repainting in place and rebuilding the graph.
 *
 * It was `id/kind/collected` per device and `id:a>b` per link, so a new snapshot with the same topology kept the
 * OLD role glyphs, state rings, cable encodings and positions on screen: measured while re-measuring the draw-call
 * budget for the "other" role glyph (a third of the sample's roles re-stated as "core" through setData left draw
 * calls and triangles byte-identical). The fast path repaints exactly one thing — the band tint and LED of each
 * body — so the signature is everything the build reads EXCEPT the device's `band`: every other device field,
 * every link field, and the layout's node positions, tier bounds and cable midpoints. A spurious rebuild costs a
 * stutter; a missed one draws a fact the snapshot no longer states. `scene.data-signature.test.ts` perturbs every
 * field, so a field added to Device or Link is covered without editing this.
 */
/** The one Device field `setData`'s fast path repaints in place (the body tint and LED), by name. */
const REPAINTED_IN_PLACE: keyof Device = "band";

export function sceneDataSignature(
  devices: readonly Device[],
  links: readonly Link[],
  layout: Pick<LayoutResult, "nodes" | "tierBounds" | "linkMidpoints">,
): string {
  /* The band is left out by KEY, never read: its value belongs to the band owner (band-read.guard.test.ts). */
  const d = JSON.stringify(devices.map((x) => Object.entries(x).filter(([k]) => k !== REPAINTED_IN_PLACE)));
  const l = JSON.stringify(links);
  const n = JSON.stringify([layout.nodes, layout.tierBounds, [...layout.linkMidpoints]]);
  return `${d}|${l}|${n}`;
}

/* A role's glyph comes from the one owner (src/core/roles.ts `roleGlyphClass`), called directly where the glyph is
   chosen: access / distribution, "other" for any other OBSERVED role, and the outlined "unobserved" mark only for a
   role the snapshot never stated. Case and whitespace are normalised there, so " Access" is access here exactly as
   it is in the legend. (A local wrapper stood here; role-glyph.test.tsx reads every call a role is handed to, and
   the owner's own function is the one legal callee.) */

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
/* (History: the body used a 0.40 wash toward white here. Superseded by BODY_BAND_TINT below.) */

/** Every profile field `buildFabricGraph` reads. Two profiles with equal keys build equal geometry. */
export function geometryKey(p: QualityProfile): string {
  return [p.anisotropy, p.chassisBevelSegments, p.chassisFineDetail, p.cableSegments, p.shadows].join("|");
}

/**
 * The light theme's body wash, lower than dark's on purpose.
 *
 * The light-theme band tokens are the DARK, AA-on-white variants (`--band-critical` #b52626), and
 * the light stage's environment specular on the lid is bright and neutral, so at the dark theme's
 * 0.40 wash the hue fell under the untinted specular and every chassis rendered the same charcoal
 * (render audit, light, real GPU: core1 Critical top 167,163,167 vs core2 Good 148,152,152). The
 * light body also moved from 0.8 to `LIGHT_BODY_STEP` in materials.ts — both halves were needed:
 * a dark albedo has no diffuse term left for any tint to ride on.
 */
/* (History: light used a 0.12 wash. Superseded by BODY_BAND_TINT below.) */

/**
 * The body tint ENVELOPE, per theme: the band token's HUE, re-expressed at one fixed saturation and
 * one fixed linear LUMINANCE before it multiplies the body albedo. Supersedes the two washes above
 * for the body (they are kept for the measurement history they carry).
 *
 * WHY (C5 critic, 2026-09-22, measured real GPU, high, 1920x1080, median lid RGB per chassis):
 *   - Light: the light band tokens are the dark, AA-on-white TEXT variants (#b52626, #a14a0a).
 *     Multiplied almost raw onto a mid-grey body every lid went dark and muddy — core1 Critical
 *     (127,91,92), a maroon blob with its vents and ports lost — and Critical vs Poor collapsed:
 *     core1 C (126,91,92) vs access8 P (122,96,91), CIE76 dE 6.2.
 *   - Dark: Critical vs Poor measured (174,143,151) vs (172,142,143), dE 3.9.
 * A text colour's darkness is chosen for 4.5:1 on white, irrelevant to a multiply on a chassis, and
 * a token washed toward white keeps only what its channels happen to differ in. What the body
 * needs from the token is its hue, so that is all it takes: hue from the token (SSOT), saturation
 * and luminance from here, identical for every band — no band is lighter or louder than another,
 * which keeps "the five band colours are within ~1.1:1 of each other in greyscale" (FabricLegend)
 * true by construction, and the label letter stays the greyscale channel.
 *
 * Equal LUMINANCE, not equal HSL lightness: at one HSL lightness a green carries ~2.5x the
 * luminance of a red, which measured as Good/Excellent lids at 2.3:1 on the light stage while the
 * Critical ones sat at 3.7:1.
 *
 * MEASURED AFTER (same probe): light — core1 C (146,89,89) vs access8 P (138,93,67), dE 14.9, every
 * collected chassis 4.39-5.16:1 against the ground 8 px outside it (3.93-5.22 before); dark —
 * access13 C (179,109,110) vs access8 P (173,112,89), every collected chassis 4.05-4.49:1. Dark's
 * lower luminance is what buys its chroma: at 0.45 / s 0.8 Critical vs Poor was still only dE 8.9.
 * See docs/render-decisions.md §7 for the table.
 */
export const BODY_BAND_TINT = {
  light: { s: 0.55, luminance: 0.22 },
  dark: { s: 1, luminance: 0.32 },
} as const;
const _hsl = { h: 0, s: 0, l: 0 };

/**
 * The band at its true hue, for the emissive channel.
 *
 * `materials.led` is built with `emissiveFromInstanceColor`, so this colour becomes RADIANCE on a
 * near-black strip rather than albedo on a blown-out lid. That is the difference between an
 * encoding and a decoration.
 *
 * The call site used to be `bandTint(...).multiplyScalar(1.4)` (a washed tint) under a comment claiming the LED
 * "carries the band at FULL saturation". It did not: it carried the body's 72 %-white wash,
 * brightened — the one channel with the headroom to distinguish the five bands was spending it on
 * a colour that had already been thrown away.
 */
function bandEmissive(device: Device, tokens: TokenPalette, out: Color): Color {
  const pres = presentBand(device);
  out.copy(tokens.color(pres.colorToken));
  if (pres.qualified) {
    // Neutral means no hue: the muted ink carries a faint blue cast that, as radiance, would read
    // as a sixth band colour. Keep its luminance, drop its chroma (see bandTint).
    const y = 0.2126 * out.r + 0.7152 * out.g + 0.0722 * out.b;
    out.setRGB(y, y, y);
  }
  return out.multiplyScalar(1.4);
}

/**
 * The band tint carried by the chassis body.
 *
 * Held at one fixed saturation and luminance (BODY_BAND_TINT) so the multiply against the body albedo shifts the hue without painting the
 * hardware. Chroma in this product is spent on severity and state; a fully saturated chassis would
 * make the furniture louder than a Critical finding, which §3.3 forbids outright.
 * `band === null` renders as `--claim-indeterminate` — never neutral grey, which reads as disabled,
 * and never `--band-good`, which would be an invented verdict.
 *
 * The token comes from the ONE band owner (core/band-qualification.ts `presentBand`), which is
 * also what the label letter, the Fabric list, the announcement and the legend read. A favourable
 * band on a host with unassessed scoring domains is QUALIFIED there and drawn in the neutral ink;
 * its tint is kept achromatic here (saturation 0), because re-expressing a grey token "at the
 * band's hue" would invent a hue — HSL reports hue 0 (red) for a grey. MEASURED before (B1,
 * 2026-09-22): podacc1 was painted the Excellent green while DevicePane drew the same band neutral.
 */
function bandTint(device: Device, tokens: TokenPalette, out: Color): Color {
  const env = BODY_BAND_TINT[tokens.theme === "light" ? "light" : "dark"];
  const pres = presentBand(device);
  out.copy(tokens.color(pres.colorToken));
  out.getHSL(_hsl, SRGBColorSpace);
  out.setHSL(_hsl.h, pres.qualified ? 0 : env.s, 0.5, SRGBColorSpace);
  // Hit the target luminance exactly: scale down when the pure hue is brighter than the target,
  // lift toward white when it is darker (a pure red tops out at Y 0.2126, so scaling alone cannot
  // reach dark's target). The working space is linear, so both are exact.
  const y = 0.2126 * out.r + 0.7152 * out.g + 0.0722 * out.b;
  if (y >= env.luminance) out.multiplyScalar(env.luminance / Math.max(y, 1e-6));
  else out.lerp(_white, (env.luminance - y) / (1 - y));
  return out;
}
const _white = new Color(1, 1, 1);

/**
 * Chroma the `up` state ring keeps. `up` is the expected state, and at full `--state-up` a mint ring
 * round all 26 nodes — the 8 Critical-band ones included — made "green rings" the dominant read of
 * the fabric instead of the band channel (C5 critic, 2026-09-22). The ring keeps its luminance, so
 * its contrast against the deck is unchanged, and its SHAPE (solid vs dashed vs double) still
 * carries the state in greyscale; only the hue that competed with severity is quietened. `down`
 * and `unknown` are the states worth noticing and stay at full chroma.
 */
export const UP_RING_CHROMA = 0.4;
function stateTint(status: string, tokens: TokenPalette, out: Color): Color {
  const token = status === "up" ? "--state-up" : status === "down" ? "--state-down" : "--state-unknown";
  out.copy(tokens.color(token));
  if (status === "up") {
    const y = 0.2126 * out.r + 0.7152 * out.g + 0.0722 * out.b;
    out.setRGB(y + (out.r - y) * UP_RING_CHROMA, y + (out.g - y) * UP_RING_CHROMA, y + (out.b - y) * UP_RING_CHROMA);
  }
  return out;
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
        s.group.body.setColorAt(s.slot, bandTint(s.device, tokens, _colour));
      }
      if (s.group.led !== null) {
        // The LED strip carries the band at its TRUE hue, as emission on a near-black recess, which is
        // what makes it legible at overview distance and what makes the encoding real; the body carries
        // the same band as a hue at fixed luminance. See BODY_BAND_TINT.
        s.group.led.setColorAt(s.slot, bandEmissive(s.device, tokens, _colour));
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

  /* Every per-device instanced mesh built outside the chassis groups carries the recession
     attribute and is registered as a mirror, so it recedes with the device it belongs to. Its
     material is emphasis-patched; without the attribute that patch reads zero and the mesh stays
     at full strength while its chassis recedes — the state rings did exactly that (C5 audit). */
  const mirrors: RecedeMirror[] = [];
  const mirrorRecede = (mesh: InstancedMesh, members: readonly DeviceSlot[]): void => {
    const attr = new InstancedBufferAttribute(new Float32Array(Math.max(1, members.length)), 1);
    attr.setUsage(DynamicDrawUsage);
    mesh.geometry.setAttribute(RECEDE_ATTRIBUTE, attr);
    mirrors.push({ attr, deviceIndex: members.map((m) => m.index) });
  };

  /* Role glyphs. One shape per owner class (ROLE_GLYPHS), one instanced mesh each, on the chassis lid where
     the default camera can actually see them. A class no device holds is an instanced mesh with count 0, which
     three.js does not draw (WebGLBufferRenderer: `if ( primcount === 0 ) return;`), so a fleet without an
     "other" role renders the same draw calls as before that glyph existed. */
  const roleGlyphs: InstancedMesh[] = [];
  for (const glyph of ROLE_GLYPHS) {
    const members = order.filter((s) => roleGlyphClass(s.device.role) === glyph);
    const geometry = buildRoleGlyph(glyph);
    const mesh = new InstancedMesh(geometry, materials.rail, Math.max(1, members.length));
    mirrorRecede(mesh, members);
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
    mirrorRecede(mesh, members);
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
  let hatchRound: InstancedMesh | null = null;
  let ghostEdges: LineSegments2 | null = null;
  if (ghostSlots.length > 0) {
    /* TWO decal shapes, one per lid shape. The access point's lid is a disc, and the square decal
       laid on it put four corners outside its silhouette — MEASURED (C5 critic, AP-floor1 dollied
       in): a spike on each side of the puck and a straight hatch edge across its round lid. The
       disc decal is sized to the lid's flat top (inside the fillet). One more draw call, and only
       while an access point is uncollected. */
    const rectSlots = ghostSlots.filter((s) => s.kind !== "ap");
    const roundSlots = ghostSlots.filter((s) => s.kind === "ap");
    const makeHatch = (geometry: BufferGeometry, members: DeviceSlot[], name: string, round: boolean): InstancedMesh => {
      const mesh = new InstancedMesh(geometry, materials.hatch, members.length);
      mesh.name = name;
      mesh.frustumCulled = false;
      mesh.renderOrder = 4;
      for (let i = 0; i < members.length; i += 1) {
        const s = members[i];
        if (s === undefined) continue;
        _pos.set(s.centre[0], s.top + 0.04, s.centre[2]);
        if (round) _scale.set(s.half[0] * 1.76, 1, s.half[2] * 1.76);
        else _scale.set(s.half[0] * 1.55, 1, s.half[2] * 1.5);
        mesh.setMatrixAt(i, _m.compose(_pos, _rot, _scale));
      }
      mesh.instanceMatrix.needsUpdate = true;
      scene.add(mesh);
      return mesh;
    };
    if (rectSlots.length > 0) hatch = makeHatch(unitDecal(), rectSlots, "uncollected-hatch", false);
    if (roundSlots.length > 0) hatchRound = makeHatch(unitDiscDecal(), roundSlots, "uncollected-hatch-round", true);

    // The wireframe is baked into world space rather than instanced: three uncollected devices do
    // not justify a second instanced pipeline, and a baked batch is one draw call either way.
    const positions: number[] = [];
    for (const s of ghostSlots) {
      const edges = chassisSilhouette(s.group.kind);
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

  /* One depth-only occluder material for every rim shell (see makeRimShell). */
  const rimOccluderMaterial = new MeshBasicMaterial({
    name: "rim-occluder",
    colorWrite: false,
    depthWrite: true,
    transparent: true,
  });
  const hoverShell = makeRimShell("hover-shell", materials.hoverShell, fallbackGeometry, rimOccluderMaterial);
  scene.add(hoverShell);

  const selectionShellMaterial = new MeshBasicMaterial({
    name: "selection-shell",
    color: tokens.color("--accent").clone(),
    side: BackSide,
    transparent: true,
    opacity: 0,
    depthWrite: false,
    toneMapped: false,
  });
  const selectionShell = makeRimShell("selection-shell", selectionShellMaterial, fallbackGeometry, rimOccluderMaterial);
  scene.add(selectionShell);

  const selectionProxy = new Mesh(fallbackGeometry, invisibleMaterial());
  selectionProxy.name = "selection-proxy";
  selectionProxy.visible = false;
  scene.add(selectionProxy);

  const blockedProxy = new Mesh(fallbackGeometry, invisibleMaterial());
  blockedProxy.name = "blocked-proxy";
  blockedProxy.visible = false;
  scene.add(blockedProxy);

  /* The blocked host's alarm, as GEOMETRY. The red outline and its glow are OutlineEffect passes,
     which the low tier does not run (quality.ts `outline: false`), so at low a blocked chassis was
     marked only by the floating stop glyph and the DOM chip — the alarm's strength depended on the
     tier (C5 audit: halo present at high, absent at low, same trace). This rim is an inverted hull
     in `--sev-critical`, the same technique as the hover shell and horizontal-only for the same
     reason (a vertical term paints across the lid), unlit and not tone-mapped so the token arrives
     as authored. It costs one draw call while a trace is blocked, at every tier: a tier change
     changes cost, not composition. */
  const blockedShellMaterial = new MeshBasicMaterial({
    name: "blocked-shell",
    color: tokens.color("--sev-critical").clone(),
    side: BackSide,
    toneMapped: false,
  });
  const blockedShell = makeRimShell("blocked-shell", blockedShellMaterial, fallbackGeometry, rimOccluderMaterial);
  scene.add(blockedShell);

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
    mirrors,
    hatch,
    hatchRound,
    ghostEdges,
    halo,
    hoverShell,
    selectionShell,
    blockedShell,
    selectionProxy,
    blockedProxy,
    materials,
    maps,
    tokens,
    signature: sceneDataSignature(devices, links, layout),
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
      for (const h of [hatch, hatchRound]) {
        if (h === null) continue;
        h.geometry.dispose();
        h.dispose();
        h.removeFromParent();
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
      selectionShellMaterial.dispose();
      selectionShell.removeFromParent();
      rimOccluderMaterial.dispose();
      (selectionProxy.material as Material).dispose();
      (blockedProxy.material as Material).dispose();
      blockedShellMaterial.dispose();
      blockedShell.removeFromParent();
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
/**
 * A SILHOUETTE rim around one chassis: an inverted hull grown horizontally (see applyHoverVisuals
 * for why never vertically), with a depth-only copy of the chassis box drawn just before it as a
 * child.
 *
 * The hull alone is a rim only over an OPAQUE chassis, whose depth hides the hull's inner floor and
 * far walls. Over a chassis that is NOT collected — a 22 % fill, a wireframe and a hatch that write
 * no depth — the hull's whole inside showed through: MEASURED (C5 audit, 2026-09-22, both tiers)
 * hovering wan-edge-rtr1.lab turned it into a near-solid box in the rim colour, erasing the
 * "not collected" treatment it was hovering. The occluder writes the chassis box's depth (and no
 * colour) immediately before the hull, so only the part of the hull OUTSIDE the chassis silhouette
 * can pass the depth test: a rim, whatever the chassis is made of. One class, one fix: the hover,
 * selection and blocked rims are all built here.
 */
function makeRimShell(name: string, material: Material, geometry: BufferGeometry, occluderMaterial: Material): Mesh {
  material.transparent = true;
  const shell = new Mesh(geometry, material);
  shell.name = name;
  shell.visible = false;
  shell.renderOrder = RIM_SHELL_ORDER;
  shell.matrixAutoUpdate = false;
  const occluder = new Mesh(geometry, occluderMaterial);
  occluder.name = `${name}:occluder`;
  occluder.renderOrder = RIM_OCCLUDER_ORDER;
  occluder.matrixAutoUpdate = false;
  shell.add(occluder);
  return shell;
}

/** Put a rim shell round `slot`'s chassis, `rim` world units wide on each horizontal side. */
function placeRimShell(shell: Mesh, slot: DeviceSlot, rim: number): void {
  const sx = 1 + rim / Math.max(1e-6, slot.half[0]);
  const sz = 1 + rim / Math.max(1e-6, slot.half[2]);
  shell.geometry = slot.group.proxyGeometry;
  _rimPos.set(slot.centre[0], slot.centre[1], slot.centre[2]);
  _rimScale.set(sx, 1, sz);
  shell.matrix.compose(_rimPos, _rimRot, _rimScale);
  const occluder = shell.children[0];
  if (occluder instanceof Mesh) {
    occluder.geometry = slot.group.proxyGeometry;
    occluder.matrix.makeScale(1 / sx, 1, 1 / sz);
  }
}
const _rimPos = new Vector3();
const _rimScale = new Vector3();
const _rimRot = new Quaternion();

/** Every chassis lid as (x, top y, z) — the camera rig's height rule (camera.ts setEyeFloor). */
function chassisLids(graph: FabricGraph): Float32Array {
  const out = new Float32Array(graph.order.length * 3);
  graph.order.forEach((s, i) => {
    out[i * 3] = s.centre[0];
    out[i * 3 + 1] = s.top;
    out[i * 3 + 2] = s.centre[2];
  });
  return out;
}

function invisibleMaterial(): MeshBasicMaterial {
  const m = new MeshBasicMaterial({ colorWrite: false, depthWrite: false, depthTest: false });
  m.name = "outline-proxy";
  return m;
}

/** The stroke floor (MIN_STROKE_PX), not design-brief §4.4's 1.4 px: §4.5 sets 2 CSS px as the
 *  minimum painted stroke anywhere on the fabric, and 1.4 was the one outline under it (C5 item 8;
 *  the factory now floors every stroke, so asking for less would be a request it silently raises). */
function buildGhostLineMaterial(tokens: TokenPalette): LineMaterial {
  const mat = createCableMaterial("solid", MIN_STROKE_PX, 0.95, { vertexColors: false });
  mat.color.copy(tokens.color("--claim-indeterminate"));
  // Display-linear edge coverage, as every cable stroke (geometry/cables.ts coverageGamma).
  setCoverageGamma(mat, coverageGamma(tokens));
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
  /**
   * The label overlay reports how many labels it ACTUALLY placed. `labelsShown` then publishes
   * that count instead of this scene's own estimate — measured (A6), the estimate said 26 of 26
   * while four labels were hidden, because it sizes boxes from character counts and never sees the
   * stranded / cut-point marks that widen them. An instrument that cannot be wrong is not one.
   */
  reportLabelsShown(n: number): void;
  /**
   * The DOM label layer reports, every tick, whether it is still CONVERGING: a name it changed fewer
   * than LABEL_MIN_DWELL_PASSES passes ago that its history-free settled pass could reverse
   * (labelResolve `labelSettleMayReverse`, acceptance C5). While true, `labelsSettled()` and
   * `converged` stay false, so the settle — and a capture — waits out the DOM dwell (at most about
   * 200 ms after the last non-forced change; it cannot deadlock). No render is requested: nothing
   * needs drawing.
   */
  reportLabelsConverging(b: boolean): void;
  /**
   * The screen rectangle a device's chassis body covers right now, in the same space as
   * `project()`, or null when it is not wholly in front of the camera. The DOM label layer keeps
   * names off REAL hardware with it — see FabricLabels.tsx `onChassis`.
   */
  chassisScreenBox(deviceId: string): { x0: number; y0: number; x1: number; y1: number } | null;
  /**
   * True once the scene is idle and its label resolver has run the history-free SETTLED pass over
   * the final camera (./labelResolve). The DOM label layer switches its own hysteresis and staggered
   * drops off on the same signal, so the label set a capture photographs is a pure function of the
   * final state (acceptance F6). False the moment anything changes again.
   */
  labelsSettled(): boolean;
  /**
   * Keyboard orbit / pan (acceptance D1): the camera moves exactly as a primary / secondary pointer
   * drag of (dx, dy) CSS pixels would — the rig replays OrbitControls' own drag handlers
   * (camera.ts `orbitBy` / `panBy`). canvasKeys.ts owns which keys call these and the step.
   */
  orbitBy(dxPx: number, dyPx: number): void;
  panBy(dxPx: number, dyPx: number): void;
  /**
   * `setSelection` for a selection the CANVAS itself just made (a click on the stage), drawn in the
   * very next frame rather than one frame later.
   *
   * `setSelection` yields one frame to the page because its caller is a React commit whose panels
   * should paint first. A canvas click commits no panel inside its input task (Fabric3D.tsx defers
   * that write past the acknowledgement, acceptance E3), so there is nothing to paint first, and
   * yielding would present the click with an unchanged canvas: the acknowledgement IS this render.
   * Idempotent with the `setSelection` the deferred commit makes later.
   */
  acknowledgeSelection(deviceId: string | null, linkId: string | null): void;
  /**
   * The reader's motion preference changed (C5-R2-1, 2026-09-27). Through this setter the scene keeps
   * running: the camera and the flow overlay take the new preference, the emphasis eases apply it from
   * their next step (under reduced motion they land on their targets, §4.8), and a tier cross-fade
   * already running finishes at FADE_MAX_STEP per frame (./emphasis `createTierFadeDriver`), and so does one
   * still held or waiting at 1, which was on screen under full motion (R4-VR2-4); only an overlay up under
   * reduced motion throughout is swapped when the new tier presents (§4.8). A host that disposes and recreates the
   * scene on a toggle instead takes the overlay down with the canvas, camera pose included. Which of
   * the two Fabric3D.tsx does is read from its source by scene.test.ts.
   */
  setReducedMotion(reduced: boolean): void;
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
  /* The capability probe's own decision, kept so every later tier's reasons can restate it for
     the tier actually in force (quality.ts `probeReasonsAt`), and the automatic tier changes since,
     in order. Reasons are COMPOSED from these two, never accumulated by copying the previous
     decision's list — which is how "full quality: ..." survived a step-down to low. */
  const probeDecision: QualityDecision = decision;
  let tierLog: string[] = [];

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
  /* What the current graph was built from, so a quality-tier change can rebuild the SAME fabric
     at the new tier's geometry detail (see `applyQuality`). */
  let sourceDevices: Device[] = opts.devices;
  let sourceLinks: Link[] = opts.links;
  let sourceLayout: LayoutResult = opts.layout;

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
    /* The depth range encloses what is DRAWN — floor, decks, cable sag — not the node sphere the
       overview is framed on (camera.ts header: a dolly-limit render clipped at both tiers). Given
       at construction so the post chain below is built against the same near/far it will render
       with. */
    depthBox: measureDrawnBounds(graph.scene),
    reducedMotion,
    width: Math.max(1, canvas.clientWidth),
    height: Math.max(1, canvas.clientHeight),
  });
  /* The eye stays above every lid in view — the polar clamp alone is an angle about a target that
     a device focus moves down to the lowest tier (camera.ts EYE_ABOVE_VISIBLE_TOP). */
  cameraRig.setEyeFloor(chassisLids(graph));

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
  /* The halo and hover-rim opacities, each a finite ease from the owner (SELECT_EASE, HOVER_EASE). */
  const haloFade = createEaseChannel(0);
  let haloTarget = 0;
  const hoverFade = createEaseChannel(0);
  let hoverTarget = 0;

  let width = Math.max(1, canvas.clientWidth);
  let height = Math.max(1, canvas.clientHeight);
  let labelBoxes = new Float32Array(graph.order.length * 4);
  let labelKept = new Uint8Array(graph.order.length);
  /** Last frame's verdict per label — the hysteresis memory. See LABEL_HYSTERESIS_PX. */
  let labelWasKept = new Uint8Array(graph.order.length);
  /** 1 when a hidden label found its box clear last frame. See the temporal half in recomputeLabels. */
  let labelPending = new Uint8Array(graph.order.length);
  /** Passes since each label's verdict last changed — the dwell (labelResolve LABEL_MIN_DWELL_PASSES). */
  let labelAge = new Uint16Array(graph.order.length).fill(0xffff);
  /** Placement class per label (see recomputeLabels) and its camera distance, the tie-break. */
  let labelClass = new Float64Array(graph.order.length);
  let labelDistance = new Float64Array(graph.order.length);
  let labelsShown = 0;
  let labelsBehindChassis = 0;
  /** Screen box (x0, y0, x1, y1) and camera distance of every chassis, per rendered frame. */
  let chassisScreen = new Float32Array(0);
  let chassisDistance = new Float32Array(0);
  /** What the DOM label layer really placed, when one is mounted. See reportLabelsShown. */
  let labelsPlaced: number | null = null;
  /** The DOM label layer is still inside its dwell. See reportLabelsConverging. */
  let domLabelsConverging = false;
  /** A pending label (see recomputeLabels) needs one more rendered frame to appear. */
  let labelsNeedFrame = false;
  /** Resolver passes since an on-screen label last left (see the staggered drops in recomputeLabels). */
  let passesSinceLabelDrop = LABEL_DROP_EVERY_FRAMES;

  let dirty = true;
  /** When the camera last moved; drives the ambient-occlusion motion suspension (PostChain.setMotion). */
  let lastCameraMotionAt = Number.NEGATIVE_INFINITY;
  /** The camera moved in this frame: the label resolver lets names leave but not appear (labelResolve). */
  let labelsCameraMoving = false;
  /** True when the last render ran with occlusion suspended, so a full still frame is still owed. */
  let motionReducedRender = false;
  /**
   * The next frame yields to the page instead of rendering, because the caller just changed what
   * the fabric SHOWS (a selection, a highlight, a trace, a focus). See `frame` for why.
   */
  let yieldToPage = false;
  let yieldedLastFrame = false;
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
  /* Counted only while the chain HAS outline effects. At low (`outline: false`) the count said 1 for
     a selection and the budget grew by a pass that never ran — 132 against a 35-call frame (C5
     audit, 2026-09-22). The selection there is the geometric rim (SELECT_RIM_PX). */
  const activeOutlines = (): number =>
    profile.outline ? (selectionOutlineActive ? 1 : 0) + (blockedOutlineActive ? 1 : 0) : 0;
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
  /** A size handed to `resize` after the first render, applied with the next composed render. */
  let pendingSize: { w: number; h: number } | null = null;
  let lastStatsEmit = 0;
  let raf = 0;
  let disposed = false;

  /** The label resolver has run its history-free pass over the current (idle) frame. */
  let labelsSettledPass = false;

  /**
   * Bumped by every change to WHAT the fabric shows (anything that calls `markDirty`), and not by a
   * camera move (`requestFrame`). The post chain's history blend may only mix a frame with a previous
   * picture of the same content (postfx.ts HISTORY_AA), so a render whose content version differs
   * from the last presented frame's is drawn plain.
   */
  let contentVersion = 0;
  /** `contentVersion` as of the last presenting render. */
  let renderedContentVersion = -1;
  /** The last presenting render mixed in a history; a plain frame is owed before `converged`. */
  let historyInLastRender = false;

  const markDirty = (): void => {
    dirty = true;
    stillFrames = 0;
    labelsSettledPass = false;
    contentVersion += 1;
  };
  /** A render is owed, but nothing the fabric SHOWS changed — only the view of it (or a pointer
   *  that may yet change a hover). */
  const requestFrame = (): void => {
    dirty = true;
    stillFrames = 0;
    labelsSettledPass = false;
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
      onNeedsFrame: requestFrame,
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
   * Where a label hangs: above the chassis's PROJECTED SILHOUETTE, not above its centre.
   *
   * `projectDevice` projects a point 2.5 units over the lid's centre. From any oblique camera the
   * lid's far edge projects ABOVE that point, so a label hung there lay across the hardware it
   * names — MEASURED (render audit #7): access16's name across its own front bezel, access10's and
   * podacc2's across their own lids. The resolver tested label against label only, so nothing
   * noticed. Taking the screen-top of the four lid corners (and the old anchor, whichever is
   * higher) puts the label's baseline on the silhouette, so a name never covers its own chassis.
   * x stays the centre's projection, so a label does not slide sideways as the camera orbits.
   */
  function projectLabelAnchor(id: string): { x: number; y: number; visible: boolean; distance: number } | null {
    const p = projectDevice(id);
    const slot = graph.slots.get(id);
    if (p === null || slot === undefined) return p;
    let top = p.y;
    for (let k = 0; k < 4; k += 1) {
      _world.set(
        slot.centre[0] + (k & 1 ? slot.half[0] : -slot.half[0]),
        slot.top,
        slot.centre[2] + (k & 2 ? slot.half[2] : -slot.half[2]),
      );
      _world.project(cameraRig.camera);
      if (_world.z > -1 && _world.z < 1) top = Math.min(top, (-_world.y * 0.5 + 0.5) * height);
    }
    /* The trace's terminal glyph floats clear of the host it marks (flow.ts :: placeTerminalGlyph).
       The label is part of the same statement, so it hangs above the glyph's projected top rather
       than across it (C5 critic: the 'dist1 ? UNDECIDED' chip was drawn over the torus). The
       glyph faces the camera, so its screen-top is its centre plus the camera's UP times its
       radius (plus a unit of clearance). */
    const marker = flow.terminalMarker();
    if (marker !== null && marker.host === id) {
      _world.set(0, 1, 0).applyQuaternion(cameraRig.camera.quaternion).multiplyScalar(marker.radius + 1);
      _world.x += marker.center[0];
      _world.y += marker.center[1];
      _world.z += marker.center[2];
      _world.project(cameraRig.camera);
      if (_world.z > -1 && _world.z < 1) top = Math.min(top, (-_world.y * 0.5 + 0.5) * height);
    }
    return { x: p.x, y: top, visible: p.visible, distance: p.distance };
  }

  /**
   * Resolve which labels survive this frame. See the LABEL_* constants for why this is a collision
   * test and not a threshold. Runs once per RENDERED frame; the scene is idle the rest of the time.
   */
  /** Project each chassis body to a screen box. NaN x0 = not in front of the camera. */
  function projectChassisBoxes(n: number): void {
    if (chassisScreen.length !== n * 4) {
      chassisScreen = new Float32Array(n * 4);
      chassisDistance = new Float32Array(n);
    }
    const cam = cameraRig.camera;
    for (let i = 0; i < n; i += 1) {
      const s = graph.order[i];
      chassisScreen[i * 4] = NaN;
      if (s === undefined) continue;
      let x0 = Infinity;
      let y0 = Infinity;
      let x1 = -Infinity;
      let y1 = -Infinity;
      let front = true;
      for (let k = 0; k < 8 && front; k += 1) {
        _world.set(
          s.centre[0] + (k & 1 ? s.half[0] : -s.half[0]),
          s.centre[1] + (k & 2 ? s.half[1] : -s.half[1]),
          s.centre[2] + (k & 4 ? s.half[2] : -s.half[2]),
        );
        _world.project(cam);
        if (!(_world.z > -1 && _world.z < 1)) front = false;
        const sx = (_world.x * 0.5 + 0.5) * width;
        const sy = (-_world.y * 0.5 + 0.5) * height;
        x0 = Math.min(x0, sx);
        y0 = Math.min(y0, sy);
        x1 = Math.max(x1, sx);
        y1 = Math.max(y1, sy);
      }
      if (!front) continue;
      chassisScreen[i * 4] = x0;
      chassisScreen[i * 4 + 1] = y0;
      chassisScreen[i * 4 + 2] = x1;
      chassisScreen[i * 4 + 3] = y1;
      _world.set(s.centre[0], s.centre[1], s.centre[2]);
      chassisDistance[i] = _world.distanceTo(cam.position);
    }
  }

  /**
   * True when label box (x0..y1) of device i would be drawn over a chassis nearer to the camera
   * than device i itself. A DOM label has no depth, so that label would sit IN FRONT of hardware
   * that is physically in front of the device it names. The chassis box is inset by
   * LABEL_OCCLUDER_INSET_PX so a label grazing a bounding-box corner (mostly empty screen) is not
   * withheld. A label over a FARTHER chassis is ordinary overlay and stays.
   */
  function labelBehindNearerChassis(i: number, x0: number, y0: number, x1: number, y1: number): boolean {
    const d = chassisDistance[i] ?? 0;
    const n = graph.order.length;
    for (let j = 0; j < n; j += 1) {
      if (j === i) continue;
      const cx0 = chassisScreen[j * 4] ?? NaN;
      if (Number.isNaN(cx0)) continue;
      if ((chassisDistance[j] ?? Infinity) >= d) continue;
      const cx1 = (chassisScreen[j * 4 + 2] ?? 0) - LABEL_OCCLUDER_INSET_PX;
      const cy0 = (chassisScreen[j * 4 + 1] ?? 0) + LABEL_OCCLUDER_INSET_PX;
      const cy1 = (chassisScreen[j * 4 + 3] ?? 0) - LABEL_OCCLUDER_INSET_PX;
      const ix0 = cx0 + LABEL_OCCLUDER_INSET_PX;
      if (ix0 >= cx1 || cy0 >= cy1) continue;
      if (x0 < cx1 && x1 > ix0 && y0 < cy1 && y1 > cy0) return true;
    }
    return false;
  }

  /**
   * `settled` = the scene is idle and its final frame has been rendered. The resolver then runs ONE
   * history-free pass (see ./labelResolve): the settled label set is a pure function of the final
   * camera and scene, not of the frames that led to it (acceptance F6). While anything moves, the
   * hysteresis, the temporal hold and the staggered drops apply as before.
   */
  function recomputeLabels(settled = false): void {
    const n = graph.order.length;
    projectChassisBoxes(n);
    for (let i = 0; i < n; i += 1) {
      labelClass[i] = 60;
      labelDistance[i] = 0;
      const s = graph.order[i];
      if (s === undefined) {
        labelBoxes[i * 4] = NaN;
        continue;
      }
      const p = projectLabelAnchor(s.id);
      if (p === null || !p.visible) {
        labelBoxes[i * 4] = NaN;
        continue;
      }
      const w = s.device.host.length * LABEL_CHAR_PX + LABEL_PAD_PX;
      labelBoxes[i * 4] = p.x - w / 2;
      labelBoxes[i * 4 + 1] = p.y - LABEL_RISE_PX - LABEL_LINE_PX;
      labelBoxes[i * 4 + 2] = p.x + w / 2;
      labelBoxes[i * 4 + 3] = p.y - LABEL_RISE_PX;
      // Lower class = higher priority. The ordering is a claim about what the user is looking at,
      // so it follows the investigation state first and the topology's own hubs second. Classes
      // below 10 are the investigation's own subjects: they are placed whatever they overlap, so
      // the overlay can draw their marks (A4, A6), and they skip the temporal hold. Within a class,
      // a label already on screen outranks one that is not (the ordering half of the hysteresis,
      // LABEL_HYSTERESIS_PX, moving camera only), then the nearer label takes the box.
      let cls = 60;
      if (s.id === selectedDevice) cls = 0;
      // Hover is urgent only on a still camera — labelResolve `labelUrgent`, the DOM layer's rule
      // too: an orbit drag's pointer crosses devices without pointing at any, and claiming a box
      // for each would drop a neighbour's name with no dwell.
      else if (s.id === hoverDevice && !labelsCameraMoving) cls = 1;
      else if (highlight?.blockedHost === s.id) cls = 2;
      else if (trace !== null && trace.hops.some((h) => h.host === s.id)) cls = 3;
      else if (highlight !== null && highlight.hosts.includes(s.id)) cls = 4;
      else if (!s.device.collected) cls = 20; // a device we never reached must not lose its name
      else if (layout.byId.get(s.id)?.tier === layout.diagnostics.rootTier.tier) cls = 10;
      labelClass[i] = cls;
      labelDistance[i] = p.distance;
    }

    /* The spatial hysteresis, the TEMPORAL hold (a hidden label must find its box clear on two
       consecutive rendered frames before it appears — measured: access6 shown for exactly one frame
       of a focus tween) and the STAGGERED DROPS (C5 critic, 2026-09-22: one wheel tick dropped ~5
       names in one frame; at most one on-screen label now leaves per LABEL_DROP_EVERY_FRAMES
       passes) all live in ./labelResolve, together with the settled pass that switches them off. */
    const state = { wasKept: labelWasKept, pending: labelPending, passesSinceDrop: passesSinceLabelDrop, age: labelAge };
    const result = resolveLabels(
      {
        boxes: labelBoxes,
        classOf: labelClass,
        distance: labelDistance,
        hysteresisPx: LABEL_HYSTERESIS_PX,
        dropEveryPasses: LABEL_DROP_EVERY_FRAMES,
        behindNearerChassis: labelBehindNearerChassis,
        settled,
        cameraMoving: labelsCameraMoving,
      },
      state,
    );
    passesSinceLabelDrop = state.passesSinceDrop;
    labelsSettledPass = settled;
    labelKept.set(result.kept);
    labelsShown = result.shown;
    labelsBehindChassis = result.behind;
    // Not markDirty(): the frame that called this clears `dirty` after rendering, which would
    // swallow the request and strand every pending label on an idle scene. The flag is honoured
    // after that clear instead.
    if (result.needsFrame) labelsNeedFrame = true;
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
    return stepEmphasis(graph, emphasis, dt, reducedMotion);
  }

  /* ── the camera's step between presented frames (the history blend's gate) ── */
  const stepViewProj = new Matrix4();
  const stepPrevViewProj = new Matrix4();
  const stepNow = new Vector3();
  const stepPrev = new Vector3();
  let stepPrevValid = false;
  let lastCameraStep = Number.POSITIVE_INFINITY;
  /* WHEN the camera will come to rest, where that is known in advance — a tween — so the history
     blend is ramped out before the landing instead of dropped on the still frame after it (postfx.ts
     `nextHistoryWeight`; acceptance report 2026-09-23, C5 (a)). The rig starts a tween's clock on
     the first update after `moveTo`, with that update's `now`, and runs it for CAMERA_TWEEN_MS; the
     frame on which it stops reporting a tween is the landing frame. Observed from outside the rig,
     so a tween re-issued while one is in flight keeps the first one's start: its arrival then reads
     EARLY, which only ramps the blend out sooner — less smoothing, never a lag landing on a still
     frame. null when no arrival is known (damping, a drag): there the step itself shrinks to the
     stop, and a still frame drains the weight in stated steps. */
  let tweenObservedFrom: number | null = null;
  let cameraArrivalInMs: number | null = null;
  /**
   * How far, in DRAWING-BUFFER pixels, the camera has moved every device anchor since the last
   * presenting render: the largest screen displacement of any chassis centre between the two
   * view-projections. Infinity before the first render, so the first frame is never blended.
   */
  function cameraStepSinceRenderPx(): number {
    const cam = cameraRig.camera;
    cam.updateMatrixWorld();
    stepViewProj.copy(cam.matrixWorld).invert().premultiply(cam.projectionMatrix);
    if (!stepPrevValid) return Number.POSITIVE_INFINITY;
    const halfW = (width * renderer.getPixelRatio()) / 2;
    const halfH = (height * renderer.getPixelRatio()) / 2;
    let max = 0;
    for (const s of graph.order) {
      stepNow.set(s.centre[0], s.centre[1], s.centre[2]).applyMatrix4(stepViewProj);
      stepPrev.set(s.centre[0], s.centre[1], s.centre[2]).applyMatrix4(stepPrevViewProj);
      const d = Math.max(Math.abs(stepNow.x - stepPrev.x) * halfW, Math.abs(stepNow.y - stepPrev.y) * halfH);
      if (d > max) max = d;
    }
    return max;
  }
  /** The view-projection `cameraStepSinceRenderPx` just computed, as the presented frame's. */
  function rememberRenderedCamera(): void {
    stepPrevViewProj.copy(stepViewProj);
    stepPrevValid = true;
  }

  /* ── selection / hover visuals ─────────────────────────────────────────── */
  /** Make (deviceId, linkId) the selection. Returns false, changing nothing, when it already is. */
  function applySelection(deviceId: string | null, linkId: string | null): boolean {
    if (deviceId === selectedDevice && linkId === selectedLink) return false;
    selectedDevice = deviceId;
    selectedLink = linkId;
    applySelectionVisuals();
    recomputeEmphasis();
    markEmphasisDirty(emphasis);
    return true;
  }

  function applySelectionVisuals(): void {
    const slot = selectedDevice === null ? undefined : graph.slots.get(selectedDevice);
    if (slot === undefined) {
      graph.selectionProxy.visible = false;
      graph.halo.visible = false;
      haloTarget = 0;
      post.setSelectionOutline([]);
      selectionOutlineActive = false;
    } else {
      refreshRims();
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
      haloTarget = SELECT_HALO_ALPHA;
    }
    /* The hover rim sits OUTSIDE the selection rim when both are on one chassis ("selection survives
       hover"), so its width depends on the selection. */
    if (hoverDevice !== null) applyHoverVisuals();

    const blockedId = highlight?.blockedHost ?? null;
    const blocked = blockedId === null ? undefined : graph.slots.get(blockedId);
    if (blocked === undefined) {
      graph.blockedProxy.visible = false;
      graph.blockedShell.visible = false;
      post.setBlockedOutline([]);
      blockedOutlineActive = false;
    } else {
      refreshRims();
      graph.blockedShell.visible = true;
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

  /** World width of `px` CSS pixels at `slot`'s chassis, from the camera as it is now. */
  function rimWorld(px: number, slot: DeviceSlot): number {
    const cam = cameraRig.camera;
    const d = Math.hypot(
      cam.position.x - slot.centre[0],
      cam.position.y - slot.centre[1],
      cam.position.z - slot.centre[2],
    );
    return (px * 2 * d * Math.tan((cam.fov * Math.PI) / 360)) / Math.max(1, height);
  }

  /** Re-fit every active rim shell to its pixel width at the current camera. Every rendered frame. */
  function refreshRims(): void {
    const sel = selectedDevice === null ? undefined : graph.slots.get(selectedDevice);
    if (sel !== undefined) placeRimShell(graph.selectionShell, sel, rimWorld(SELECT_RIM_PX, sel));
    const blockedId = highlight?.blockedHost ?? null;
    const blk = blockedId === null ? undefined : graph.slots.get(blockedId);
    if (blk !== undefined) placeRimShell(graph.blockedShell, blk, rimWorld(BLOCKED_RIM_PX, blk));
    const hov = hoverDevice === null ? undefined : graph.slots.get(hoverDevice);
    if (hov !== undefined) {
      // Outside the selection rim when the hovered chassis is also the selected one.
      const px = HOVER_RIM_PX + (hoverDevice === selectedDevice ? SELECT_RIM_PX : 0);
      placeRimShell(graph.hoverShell, hov, rimWorld(px, hov));
    }
  }

  function applyHoverVisuals(): void {
    const slot = hoverDevice === null ? undefined : graph.slots.get(hoverDevice);
    if (slot === undefined) {
      hoverTarget = 0;
    } else {
      // A uniform scale would give a fat rim on the short axis; scaling by a constant WORLD
      // thickness on each axis keeps the rim visually even on a 15 x 3 x 9 box.
      //
      // HORIZONTAL ONLY. The shell used to grow vertically by the same world thickness, and that
      // is what bleached a hovered chassis: from the default camera and at close dolly, the part
      // of the enlarged hull standing above the lid was drawn as a translucent --text sheet across
      // the whole top face (render audit, both tiers: access12's lid went pale grey with a lighter
      // patch and lost its band colour). A/B with the shell forced opaque red: with the vertical
      // term the entire lid turned red; without it only a clean rim around the footprint did, and
      // the lid kept its colour. The rim the brief asks for (§4.7, "a rim on the chassis") is the
      // silhouette seen from above, which the horizontal growth alone draws.
      //
      // And a SILHOUETTE only: `makeRimShell` hides the hull wherever the chassis itself is, so the
      // hover never tints the interior of a not-collected chassis (C5 audit, 2026-09-22). Outside
      // the selection rim when the hovered chassis is also the selected one.
      refreshRims();
      graph.hoverShell.visible = true;
      hoverTarget = HOVER_RIM_OPACITY;
    }
    markDirty();
  }

  function animateFades(dt: number): boolean {
    /* Two finite eases from the owner (./emphasis): the hover rim over HOVER_EASE and the halo over
       SELECT_EASE. Each lands EXACTLY on its target on the first frame at or after its duration, so
       the final opacity is the target and never a function of how many frames the ease got
       (acceptance F6); under reduced motion each lands on the frame its target changes. */
    let moving = false;
    if (stepEaseChannel(hoverFade, HOVER_EASE, hoverTarget, dt, reducedMotion)) {
      graph.materials.hoverShell.opacity = hoverFade.value;
      graph.hoverShell.visible = hoverFade.value > 0.004;
      moving = true;
    }
    if (stepEaseChannel(haloFade, SELECT_EASE, haloTarget, dt, reducedMotion)) {
      graph.materials.halo.opacity = haloFade.value;
      graph.halo.visible = haloFade.value > 0.002;
      moving = true;
    }
    const haloAlpha = haloFade.value;
    /* The selection rim rides the halo's 140 ms fade (design-brief §4.8: "selection rim + halo
       fade-in"), so the two are one ease and land together. */
    const rimAlpha = Math.min(1, haloAlpha / SELECT_HALO_ALPHA);
    const shellMat = graph.selectionShell.material as MeshBasicMaterial;
    if (shellMat.opacity !== rimAlpha || graph.selectionShell.visible !== rimAlpha > 0.02) {
      shellMat.opacity = rimAlpha;
      graph.selectionShell.visible = rimAlpha > 0.02;
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
      return s === undefined
        ? null
        : { x: s.centre[0], y: s.centre[1], z: s.centre[2], top: s.top, half: s.half };
    },
  };

  /* ── resize ────────────────────────────────────────────────────────────── */
  /**
   * A pixel-ratio change owed by a post-chain rebuild, applied in the render loop immediately
   * before the first composed frame of the new chain (see applySize).
   */
  let pendingPixelRatio: number | null = null;

  /**
   * `deferCanvas`: the caller is about to rebuild the chain and restart the warm-up, which paints
   * nothing for several frames. `renderer.setPixelRatio` assigns `canvas.width`, and assigning
   * it — even to the SAME value — clears the drawing buffer. So a tier change used to wipe the
   * canvas at once and leave it wiped until the warm-up finished: measured, the first frame after
   * setQuality filled 0.0155 of the node region against a settled 0.446, in 5 of 6 switches on a
   * real GPU and 2 of 2 in software (review/_audit3_pop.mjs; pop-0.png is labels over an empty
   * canvas). The adaptive step-down takes the same path unasked. Now the old frame stays on screen
   * until the new chain can render, and the buffer is resized in the same animation frame as that
   * render — so no composited frame is ever blank.
   */
  function applySize(w: number, h: number, deferCanvas = false): void {
    width = Math.max(1, Math.round(w));
    height = Math.max(1, Math.round(h));
    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio;
    // Two separate knobs, deliberately not conflated: DPR is capped for sharpness, renderScale is
    // the adaptive-quality lever. `effectivePixelRatio` is the only place they meet, and the floor
    // it must respect at every tier is quality.ts :: MIN_PIXEL_RATIO.
    const ratio = effectivePixelRatio(profile, dpr);
    if (deferCanvas && firstRendered) {
      pendingPixelRatio = ratio === renderer.getPixelRatio() ? null : ratio;
    } else {
      pendingPixelRatio = null;
      if (ratio !== renderer.getPixelRatio()) renderer.setPixelRatio(ratio);
    }
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
    (graph.blockedShell.material as MeshBasicMaterial).color.copy(tokens.color("--sev-critical"));
    (graph.selectionShell.material as MeshBasicMaterial).color.copy(tokens.color("--accent"));
    graph.cables.retint(tokens);
    if (graph.ghostEdges !== null) graph.ghostEdges.material.color.copy(tokens.color("--claim-indeterminate"));
    lightingModule.retint(tokens);
    post.retint(tokens);
    flow.retint(tokens);

    for (const s of graph.order) {
      if (s.ghost) continue;
      if (s.group.body !== null) s.group.body.setColorAt(s.slot, bandTint(s.device, tokens, _colour));
      if (s.group.led !== null) {
        s.group.led.setColorAt(s.slot, bandEmissive(s.device, tokens, _colour));
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

    /* RESPONSIVENESS FIX, 2026-09-21 (acceptance E5: theme toggle measured at up to 711 ms). The
       new environment is NOT generated here: `createEnvironment` links the prefilter's programs and
       draws through them in one call, inside the click that changed the theme. Clearing it hands
       the work to the warm-up restarted below, which prepares the programs, yields while the driver
       links them, and generates in a frame of its own — the same path as the cold load. Nothing
       renders until the warm-up finishes, so no frame is ever drawn without an environment. */
    environment?.dispose();
    environment = null;
    graph.scene.environment = null;

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
   * and not the cost. The rebuild costs a few frames of warm-up, during which the PREVIOUS frame
   * stays on the canvas (applySize defers the buffer resize to the first composed frame), so the
   * change is a swap, never a blank frame.
   */
  /**
   * Rebuild the scene graph from `source*` at the current `profile`.
   *
   * `reframe` is true only for new DATA: a new layout owns a new home framing. A quality-tier
   * rebuild keeps the layout, so it must not touch the camera — nothing but an explicit action
   * moves it (design-brief.md §4.4).
   */
  function rebuildGraph(reframe: boolean): void {
    const previous = graph;
    graph.scene.remove(flow.group);
    lightingModule.group.removeFromParent();
    graph = buildFabricGraph({ devices: sourceDevices, links: sourceLinks, layout: sourceLayout, theme, profile });
    layout = layoutOf(sourceLayout);
    graph.scene.background = backdrop.texture;
    if (environment !== null) {
      graph.scene.environment = environment.texture;
      graph.scene.environmentIntensity = environment.intensity;
    }
    graph.scene.add(lightingModule.group);
    graph.scene.add(flow.group);
    lightingModule.fit(layout.bounds);
    previous.dispose();
    cameraRig.setDepthBounds(measureDrawnBounds(graph.scene));
    cameraRig.setEyeFloor(chassisLids(graph));

    /* The label resolver's state is CARRIED ACROSS the rebuild, by device id. Zeroing it made
       `project()` report every label invisible until the next rendered frame re-resolved them, and
       the temporal hysteresis then held each one back a further frame — so a quality-tier change
       (manual, or the automatic step-down) blanked every device name for a frame or two (C5 audit:
       no labels in the first frame after setQuality('low'), all back 100 ms later). Labels drop by
       count with hysteresis; they never pop (design-brief.md §4.4). A device new to this graph
       starts hidden and earns its box like any other. */
    const carriedKept = new Map<string, number>();
    for (let i = 0; i < previous.order.length; i += 1) {
      const s = previous.order[i];
      if (s !== undefined) carriedKept.set(s.id, labelKept[i] ?? 0);
    }
    emphasis = createEmphasisState(graph.order.length);
    labelBoxes = new Float32Array(graph.order.length * 4);
    labelKept = new Uint8Array(graph.order.length);
    labelWasKept = new Uint8Array(graph.order.length);
    labelPending = new Uint8Array(graph.order.length);
    labelAge = new Uint16Array(graph.order.length).fill(0xffff);
    for (let i = 0; i < graph.order.length; i += 1) {
      const s = graph.order[i];
      if (s === undefined) continue;
      const kept = carriedKept.get(s.id) ?? 0;
      labelKept[i] = kept;
      labelWasKept[i] = kept;
    }
    labelClass = new Float64Array(graph.order.length);
    labelDistance = new Float64Array(graph.order.length);
    markEmphasisDirty(emphasis);
    if (reframe) {
      cameraRig.setHomeFraming(
        layout.framing,
        {
          center: layout.framing.boundingSphere?.center ?? centreOf(layout),
          radius: layout.framing.boundingSphere?.radius ?? radiusOf(layout),
        },
        layout.bounds,
      );
    }
    post.setBloomObjects([...graph.emissiveObjects, ...flow.emissiveObjects()]);
    applySize(width, height, true);
    recomputeEmphasis();
    applySelectionVisuals();
    applyHoverVisuals();
    compiled = false;
    restartWarmup();
    markDirty();
  }

  /* ── tier cross-fade ───────────────────────────────────────────────────────
   *
   * A tier change swaps SMAA preset, SSAO and the outlines in ONE frame. MEASURED (C5 audit,
   * Intel D3D11, setQuality('low') during a trace): 3.61% of the canvas changed between two
   * screenshots 120 ms apart, outlining every chassis edge, ring and dashed link — a pop, and the
   * automatic step-down can trigger it in the middle of a session.
   *
   * So the OLD tier's picture is copied to a 2-D canvas laid over the WebGL one before the chain is
   * torn down. It holds through the re-warm-up (so no half-built frame is ever seen either) and,
   * once the new tier has presented its first frame underneath, fades out over TIER_FADE_MS (./emphasis) — a
   * true cross-fade between the two tiers' frames. Reduced motion removes it in one step on that
   * same frame instead: a swap, never an animation.
   *
   * STEPPED, NOT TRANSITIONED (C5, 2026-09-26). The fade used to be a CSS transition, and a CSS
   * transition runs on the wall clock: MEASURED at 7f67013 (dark, high -> low, pixel copy off), the
   * overlay went 1 -> 0.64 across ONE 116.6 ms host frame — a cut, against the 0.25 bar — after the
   * hold below had seen three calm frames. A hold predicts future frames from past ones; it cannot
   * stop a stall that has not happened yet. So the overlay's opacity is now written once per frame by
   * `frame()`, through `createTierFadeDriver` (./emphasis, the ease owner). That is the same 280 ms
   * ease-in-out, on the frame's REAL duration, but never more than FADE_MAX_STEP (0.2) per frame.
   * After a stall it moves 0.2 and catches up with the curve. At 60 Hz the cap never binds on this
   * ease, so the look is unchanged. A stall of about 33 ms or more can engage it, and a stall can then
   * push the end past 300 ms: a delay, not a cut. The measured and modelled envelope is at TIER_FADE_MS
   * in ./emphasis. The overlay leaves on the frame the value reaches exactly 0 — not on a
   * `TIER_FADE_MS + 50` timer, which (armed when the fade was asked to start, not when it did) could
   * remove an overlay still at 0.32 opacity after a 160 ms late start: a cut by removal. It owes no
   * WebGL render: the overlay is DOM, and `frame()` runs on every animation frame whether or not it
   * renders.
   *
   * HANDED OVER, NEVER CUT (C5-R2-1, 2026-09-27). A tier change that lands while an overlay is up — a
   * `setQuality` mid-fade, an automatic step-down, the step-up a tab switch queues for the first frame
   * back — used to run `clearTierFade()` first: the half-faded overlay vanished in one frame and a copy
   * of the canvas UNDER it took its place (verifier round 2: a 0.4-1.0 cut of the pop the fade hides).
   * `snapshotForTierFade` now hands over (`handOverTierFade`, ./emphasis): the new overlay is the frame
   * the canvas shows with the running overlay drawn in at its CURRENT opacity, so at 1 it is the
   * picture the reader saw, and it fades from there (the compose is ./emphasis `tierFadeCopy`). A tier
   * change asked for while a fade runs through a warm-up (a theme change, new data) cannot be copied
   * yet, and is DEFERRED until the warm-up has presented (`deferredQuality`, landed by `frame()`): landed
   * at once, the new tier's first frame came up under the fade's partial value, (1 - that value) of its
   * pop uncovered (R4-VR1-5). Held at 1, an overlay just waits for the new tier's first frame again.
   * Only a copy that FAILS outright (no 2-D context, a draw that throws) leaves a fading overlay to run
   * on from its value: the host on which, with nothing up, a tier change has no cross-fade at all. The
   * driver has no watchdog either (./emphasis `createTierFadeDriver`). The overlay's whole life —
   * mount, hand-over, hold, fade, removal — is ./emphasis `createTierFadeSlot`, executed there; this
   * file lends it the page (mount, unmount, write). Every site in this file that touches the DOM —
   * found by TYPE, not by name — is enumerated by scene.test.ts and held to a stated reason;
   * emphasis.test.ts executes the class through the slot on a model of the screen, and
   * review/capture-motion.mjs measures it in a browser (a tier change mid-hold, mid-fade and on the
   * first frame back from a hidden tab).
   *
   * STARTED ONE FRAME LATE (C5 critic, 2026-09-22: "a hard cut in a single frame"; the fade was 300 ms then).
   * Measured in-page with a per-rAF opacity trace on a real GPU: the overlay held for 289 ms, then
   * went 0.92 -> 0.50 across ONE 91 ms frame — the new chain's first composed frame is the heavy
   * one, and a CSS transition started in the same task as that render spends its first half inside
   * it. Sampled by screenshots ~250 ms apart the remaining 100 ms could not register at all, so a
   * working fade read as a cut. The transition now starts on the animation frame AFTER the new
   * tier has presented, and runs long enough to span several ordinary frames.
   *
   * The duration and its reasoning (280 ms, not 300: acceptance C6) live with the ease in
   * ./emphasis (`TIER_FADE_MS`, `TIER_FADE_EASE`), held by `src/core/motion-inventory.test.ts`
   * against its §4.8 row. */
  /* The overlay itself: ./emphasis `createTierFadeSlot` owns its life (mount, hand-over, hold, fade,
     removal) and is executed in emphasis.test.ts. This is the page it is lent, and all of it. */
  const tierFade = createTierFadeSlot<HTMLCanvasElement>({
    mount: (el) => {
      canvas.parentElement?.appendChild(el);
    },
    unmount: (el) => {
      el.remove();
    },
    write: (el, opacity) => {
      el.style.opacity = String(opacity);
    },
  });
  /** The hold's start backstop (see `releaseTierFade`); a stale one is harmless (its hold is no longer live). */
  let tierFadeBackstop: ReturnType<typeof setTimeout> | null = null;
  /** A tier change asked for while a fade ran through a warm-up: landed by `frame()` once the warm-up has
   *  presented, so it is handed over from the fade's value (R4-VR1-5). The last one asked for wins. */
  let deferredQuality: QualityDecision | null = null;

  /** A tier change: hand the overlay over to a copy of the frame on screen (`handOverTierFade`,
   *  ./emphasis). Must run before the old chain or graph is disposed. False when the change must wait
   *  for the warm-up in progress (`deferred`). */
  function snapshotForTierFade(): boolean {
    return tierFade.tierChange(copyFrameForTierFade, !compiled).kind !== "deferred";
  }

  /** Copy the frame the OLD tier draws into a new overlay element (not yet on the page), or null when
   *  there is nothing to copy. The handover draws a running overlay over it. */
  function copyFrameForTierFade(): TierFadeCopy<HTMLCanvasElement> | null {
    const parent = canvas.parentElement;
    /* Nothing to cross-fade from while the canvas has never shown a complete frame. */
    if (parent === null || typeof document === "undefined" || !compiled || !firstRendered) return null;
    const w = canvas.width;
    const h = canvas.height;
    if (w === 0 || h === 0) return null;
    let ctx: CanvasRenderingContext2D | null = null;
    const el = document.createElement("canvas");
    try {
      el.width = w;
      el.height = h;
      ctx = el.getContext("2d");
    } catch {
      ctx = null;
    }
    if (ctx === null) return null;
    /* The default framebuffer is not preserved between frames, so the frame on screen cannot be read
       back later. Re-presenting it through the old chain in this same task makes the drawing buffer
       hold it for the copy below. One frame at the old tier, paid only on a tier change. */
    try {
      /* ...with the history weight the loop would give this frame, not a plain one. An unset weight
         is 0, and this re-render IS presented (it becomes the overlay): taken mid-creep, a plain one
         dropped the blend 0.75 -> 0 in one frame — part of the 6.08x change the C5 grading measured
         at the light/high orbit's step-down (2026-09-23). */
      post.setHistoryWeight(
        nextHistoryWeight(post.historyWeightUsed(), cameraStepSinceRenderPx(), contentVersion !== renderedContentVersion, cameraArrivalInMs, lastFrameMs),
      );
      post.render(0);
      ctx.drawImage(canvas, 0, 0);
    } catch {
      return null;
    }
    el.className = "fabric3d__tier-fade";
    el.setAttribute("aria-hidden", "true");
    el.dataset.testid = "fabric3d-tier-fade";
    el.style.cssText =
      "position:absolute;inset:0;inline-size:100%;block-size:100%;pointer-events:none;opacity:1;";
    /* The handover draws a running overlay over this copy at its current opacity, stretched to the
       whole copy as CSS stretches it (inset: 0): the ease owner's compose, executed in
       emphasis.test.ts against a compositing 2-D context (R4-V1-2). */
    return tierFadeCopy<HTMLCanvasElement>(el, ctx, w, h);
  }

  /** Called after a composed frame lands on the canvas (at `now`): release the old tier's picture. */
  function releaseTierFade(now: number): void {
    /* Only a HELD overlay (at exactly 1) is released. Under reduced motion the slot swaps it away on
       this frame if it has been up under reduced motion throughout (§4.8: a swap, not an animation — the
       same as having had no overlay), and starts it at the cap if it was shown under full motion
       (R4-VR2-4); otherwise it
       hands back its hold, and this decides when the fade starts. From then on `frame()` drives it:
       the driver steps it on the frame's raw duration (capped at FADE_MAX_STEP per frame), writes the
       overlay's opacity, and removes it on the frame it reaches exactly 0. It holds no timer: a hidden
       tab pauses it, and the first frame back moves it by the cap (C5-R2-1). Executed in
       emphasis.test.ts. */
    const handle = tierFade.presented(reducedMotion);
    if (handle === null) return;
    if (tierFadeBackstop !== null) clearTimeout(tierFadeBackstop);
    tierFadeBackstop = null;
    /* One frame late: the heavy first composed frame of the new chain is being presented now, and a
       transition begun in it would spend itself inside that frame. A setTimeout backstop covers a
       context where rAF is suspended (the fade then starts at once rather than never). */
    if (typeof requestAnimationFrame === "function") {
      /* ...and not until the new tier's frames are ORDINARY ones. One frame late was not enough
         going UP a tier (C5 critic, 2026-09-22, "bloom halos appear in one frame"). MEASURED with a
         per-rAF opacity trace, dark, real GPU: high -> low faded smoothly over 300 ms, but
         low -> high went 1 -> 0.94 and then stalled in one 210 ms frame (the high chain's
         remaining program links / first SSAO + bloom targets) that swallowed the whole fade, so
         the next frame read 0.056: a cut. The fade therefore waits for ordinary frames — but only
         while the view under the overlay is the one it was taken from (`createTierFadeHold` in
         ./stepdown, which carries the rule, its bound and the C5 measurement that shaped it: a
         step-down mid-orbit on a contended host held a frozen frame for ~1,000 ms). The first
         frame on which the camera moved or the content changed starts the fade. */
      let started = false;
      const once = (): void => {
        if (started) return;
        started = true;
        handle.start();
      };
      const hold = createTierFadeHold(now);
      const heldContent = contentVersion;
      /* Reads the loop's own per-frame interval (`lastFrameMs`, measured for every frame in
         `frame`) and its camera-motion stamp rather than a clock of its own; `frame` runs before
         this in each animation frame (it was queued first). It only decides WHEN the overlay's
         fade begins, and the frame underneath is the new tier's frame either way. */
      const watch = (): void => {
        if (started || !handle.live) return;
        if (hold.frame(lastNow, lastFrameMs, lastCameraMotionAt > now || contentVersion !== heldContent)) once();
        else requestAnimationFrame(watch);
      };
      requestAnimationFrame(watch);
      tierFadeBackstop = setTimeout(once, TIER_FADE_HOLD_DEFAULTS.maxHoldMs);
    } else {
      handle.start();
    }
  }

  function applyQuality(next: QualityDecision): void {
    /* A tier change always goes through the handover first. One asked for while a fade runs through a
       warm-up waits for that warm-up to present (`deferredQuality`, landed by `frame()`), so it is
       handed over from the fade's value instead of landing under it (R4-VR1-5). */
    if (!snapshotForTierFade()) {
      deferredQuality = next;
      judgeQueue.length = 0;
      return;
    }
    deferredQuality = null;
    decision = next;
    const builtFrom = profile;
    profile = profileFor(next.tier);
    /* GEOMETRY FOLLOWS THE TIER, not the history. The graph used to be built once, at whatever tier
       the session booted on, and a later tier change swapped only lighting and post-processing —
       so "low" meant two different pictures depending on how the session got there (render audit,
       same host: SwiftShader booted at low drew 46,414 triangles, a GPU stepped from high to low
       drew 78,290; an uncollected chassis was a see-through wireframe on one and read as opaque
       on the other). Rebuilding here costs a warm-up the tier change already pays for. */
    if (geometryKey(builtFrom) !== geometryKey(profile)) rebuildGraph(false);
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
    graph.ground.pads.receiveShadow = profile.shadows;

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
    applySize(width, height, true);
    stepDown.reset();
    rateBar.reset();
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
      /* The passes that draw the FABRIC itself (RenderPass, NormalPass) hold `graph.scene`, whose
         programs the "scene-programs" stage already compiled against the composer's buffer. Compiling
         it again here, with the canvas bound, created a canvas-space variant of every chassis
         program that nothing ever draws with — measured on a cold load: fifteen scene programs
         linked twice, the second set pure driver time and GPU memory. */
      if (passScene === graph.scene) continue;
      /* Compiled against the target the pass will DRAW into. three's program key carries the
         output colour space, which is the renderer's for the canvas and linear for every render
         target, so a pass compiled canvas-bound but drawing into a buffer got the wrong variant and
         linked the right one at first use — measured as 70-150 ms `getProgramInfoLog` stalls on
         DepthDownsampling, Luminance and EdgeDetection inside the pass-by-pass warm-up frames.
         Only the last pass renders to the screen; every other pass writes a buffer, and any buffer
         gives the same (linear, untone-mapped) variant, so the composer's input buffer stands in. */
      const toScreen = (pass as unknown as { renderToScreen?: boolean }).renderToScreen === true;
      const previous = renderer.getRenderTarget();
      renderer.setRenderTarget(toScreen ? null : post.composer.inputBuffer);
      renderer.compile(passScene, passCamera);
      renderer.setRenderTarget(previous);
    }
  }

  /**
   * Create every program the composed frame will USE — including the ones no scene graph reaches —
   * without using any of them, so the driver links them on its own thread and "linking" can wait
   * for them by polling instead of by blocking.
   *
   * WHY. compilePostPrograms reaches only each top-level pass's fullscreen mesh. Everything an
   * effect draws INTERNALLY — the outline effects' depth/mask/edge/blur passes, SSAO's normal and
   * depth-downsampling passes, the bloom's mip pyramid and luminance passes, SMAA's edge and weight
   * passes, override-material draws of the fabric itself — only comes into existence while the
   * chain is rendering, and three links a program at its first USE, synchronously. The pass-by-pass
   * warm-up spread that over frames but could not make any one of them non-blocking: MEASURED
   * 2026-09-21 on the release build (Intel iGPU, ANGLE D3D11, CPU profile): single warm-up frames
   * of 176-280 ms, 257-275 ms of it `getProgramInfoLog` inside `WebGLProgram.getUniforms ->
   * onFirstUse`, landing in the presentation of a query clear, a viewport resize and a path-trace
   * navigation after a tier change or theme change; and the 609 ms cold-load FrameRequestCallback
   * acceptance E5 attributes to this chunk is the same shape.
   *
   * HOW. The chain is rendered ONCE with the renderer's draw and clear entry points replaced by a
   * recorder: every (material, object, scene, camera, render target) the frame would draw is
   * captured, nothing is drawn, nothing is cleared, the canvas is untouched. Each captured draw is
   * then compiled through three's own `compile()` against the render target it would have drawn
   * into — the program key carries that target's colour space and tone mapping — using a
   * prototype-chained stand-in for the object so the material override (a depth or normal pass
   * drawing the fabric with ITS material) reaches `getProgram` with the real object's instancing,
   * attributes and shadow flags. `compile()` calls `gl.linkProgram` and returns: no first use, no
   * wait. The "linking" stage then polls COMPLETION_STATUS_KHR as it already did, and the "passes"
   * stage that follows renders through programs that are already linked.
   *
   * The outline effects only run their internal passes when something is selected or
   * `forceUpdate` is set, so for the recording ONLY every effect's `forceUpdate` is set and then
   * restored; otherwise the first selection of the session would link them in the frame that
   * presents the click. Where the recorder cannot see a program (a draw that bypasses the renderer)
   * that program simply links at first use as before — the fallback is the old behaviour, never a
   * wrong frame.
   */
  /**
   * Run `fn` with every interaction visual — the selection proxy and halo, the blocked proxy and
   * shell, the hover shell — VISIBLE and in its outline selection, then put all of it back exactly.
   *
   * WHY (acceptance E3, 2026-09-22). Both warm-up compile paths see only what is visible:
   * `renderer.compile` walks `traverseVisible`, and the recorder above sees only what the chain
   * draws, which for an outline effect with an EMPTY selection is its fullscreen passes and none of
   * its mask/depth draws of a selected mesh. At cold load nothing is selected, so the halo's,
   * the shells' and the proxies' own programs, and each outline effect's mask variant for a plain
   * Mesh, were first linked in the frame that presented the FIRST selection of the session.
   * MEASURED on a production build (real GPU, host 67 % busy, review/_r3d_probe.mjs j1): the first
   * finding selected put a 69-93 ms Fabric3D FrameRequestCallback on the interaction's path, every
   * later one 0-17 ms script; under the E3 audit's 77 %-busy host that one frame was 160-338 ms.
   * Nothing is drawn by either caller (the recorder replaces draw and clear; compile draws
   * nothing), so priming changes no pixel.
   */
  function withInteractionVisualsPrimed(fn: () => void): void {
    const firstSlot = graph.slots.values().next().value;
    if (firstSlot === undefined) {
      fn();
      return;
    }
    const meshes = [graph.selectionProxy, graph.halo, graph.blockedProxy, graph.blockedShell, graph.hoverShell, graph.selectionShell];
    const saved = meshes.map((m) => ({ m, visible: m.visible, geometry: m.geometry }));
    for (const m of meshes) {
      if (m !== graph.halo) m.geometry = firstSlot.group.proxyGeometry;
      m.visible = true;
    }
    post.setSelectionOutline([graph.selectionProxy]);
    post.setBlockedOutline([graph.blockedProxy]);
    try {
      fn();
    } finally {
      for (const x of saved) {
        x.m.visible = x.visible;
        x.m.geometry = x.geometry;
      }
      post.setSelectionOutline(selectionOutlineActive ? [graph.selectionProxy] : []);
      post.setBlockedOutline(blockedOutlineActive ? [graph.blockedProxy] : []);
    }
  }

  function discoverPostPrograms(): void {
    type Draw = { material: Material; object: Object3D; scene: Object3D; camera: Camera; target: WebGLRenderTarget | null };
    const draws: Draw[] = [];
    const seen = new Set<string>();
    const r = renderer as unknown as {
      renderBufferDirect: (camera: Camera, scene: Object3D | null, geometry: unknown, material: Material, object: Object3D, group: unknown) => void;
      clear: (...a: unknown[]) => void;
      copyFramebufferToTexture?: (...a: unknown[]) => void;
    };
    const originalDraw = r.renderBufferDirect;
    const originalClear = r.clear;
    const originalCopy = r.copyFramebufferToTexture;
    const forced: { effect: { forceUpdate?: boolean }; was: boolean | undefined }[] = [];
    for (const pass of post.composer.passes) {
      const effects = (pass as unknown as { effects?: unknown[] }).effects;
      if (!Array.isArray(effects)) continue;
      for (const e of effects) {
        const effect = e as { forceUpdate?: boolean };
        if (typeof effect.forceUpdate === "boolean") {
          forced.push({ effect, was: effect.forceUpdate });
          effect.forceUpdate = true;
        }
      }
    }
    const previousTarget = renderer.getRenderTarget();
    r.renderBufferDirect = (camera, scene, geometry, material, object) => {
      if (scene === null || material === null || material === undefined) return;
      const target = renderer.getRenderTarget();
      /* Deduplicated on what three's program key can see of the draw, not on the object: two
         hundred instanced chassis drawn with one material are one program, and compiling each of
         them would spend the frame this stage exists to save. */
      const o = object as Object3D & {
        isInstancedMesh?: boolean;
        isSkinnedMesh?: boolean;
        isBatchedMesh?: boolean;
        instanceColor?: unknown;
      };
      const geo = (geometry ?? {}) as { attributes?: Record<string, unknown>; morphAttributes?: Record<string, unknown> };
      const key = [
        material.uuid,
        o.isInstancedMesh === true ? "I" : "-",
        o.instanceColor !== null && o.instanceColor !== undefined ? "C" : "-",
        o.isSkinnedMesh === true ? "S" : "-",
        o.isBatchedMesh === true ? "B" : "-",
        o.receiveShadow ? "R" : "-",
        Object.keys(geo.attributes ?? {}).sort().join(","),
        Object.keys(geo.morphAttributes ?? {}).sort().join(","),
        target === null ? "canvas" : target.texture.uuid,
        scene.uuid,
      ].join("|");
      if (seen.has(key)) return;
      seen.add(key);
      draws.push({ material, object, scene, camera, target });
    };
    r.clear = () => undefined;
    if (originalCopy !== undefined) r.copyFramebufferToTexture = () => undefined;
    try {
      post.render(0);
    } catch {
      /* A recording that throws part-way still compiled what it saw; the rest links at first use. */
    } finally {
      r.renderBufferDirect = originalDraw;
      r.clear = originalClear;
      if (originalCopy !== undefined) r.copyFramebufferToTexture = originalCopy;
      for (const f of forced) f.effect.forceUpdate = f.was;
    }
    for (const d of draws) {
      /* A stand-in that IS the object for every property three's program key reads (instancing,
         instance colour, morph targets, geometry attributes, shadow flags) but carries the material
         the frame drew it with, so an override material is keyed against the object it overrides. */
      const stand = Object.create(d.object) as Object3D & { material: Material };
      stand.material = d.material;
      const only = {
        traverse: (cb: (o: Object3D) => void) => cb(stand),
        traverseVisible: () => undefined,
      } as unknown as Object3D;
      renderer.setRenderTarget(d.target);
      try {
        renderer.compile(only, d.camera, d.scene as Scene);
      } catch {
        /* Same fallback: this draw's program links at first use. */
      }
    }
    renderer.setRenderTarget(previousTarget);
  }

  /**
   * Re-run the warm-up because new programs are about to exist: a theme change, a quality-tier
   * rebuild, or a topology change. Programs already linked report ready on the first poll, so an
   * unchanged chain costs two frames rather than a second link wait.
   */
  function restartWarmup(): void {
    warmupStage = "yield";
    /* Publish the restarted warm-up on the very next frame instead of up to 500 ms later. The
       "yield" stage renders nothing, so that frame is where the stage's "Building the 3-D fabric"
       progress affordance gets painted — BEFORE the pass-by-pass link frames that follow a tier
       step-down or theme change. Measured by review/audit-e5-sweep.mjs: without this, those frames
       (230-580 ms on a busy host) ran with nothing on screen saying why the view had stopped. */
    lastStatsEmit = 0;
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
    const done = runWarmupPassStep(
      passes,
      passEnabled,
      warmupPass,
      () => mark("atlas:warmup-pass", () => post.render(0)),
      withInteractionVisualsPrimed,
    );
    warmupPass += 1;
    return done;
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
        withInteractionVisualsPrimed(() => renderer.compile(graph.scene, cameraRig.camera));
        renderer.setRenderTarget(previous);
      });
      warmupStage = "post-programs";
      return false;
    }
    if (warmupStage === "post-programs") {
      mark("atlas:warmup-post-programs", compilePostPrograms);
      mark("atlas:warmup-discover-programs", () => withInteractionVisualsPrimed(discoverPostPrograms));
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
  const stepDown = createStepDownJudge();
  /* The display's presentation period, measured on frames that drew nothing — see
     `createPresentationCadence` in ./stepdown. Handed to the judge so a display presenting at 30 Hz
     (a power governor) is not read as a renderer missing a 60 Hz budget. */
  const cadence = createPresentationCadence();
  /** Whether the previous rAF callback drew nothing, so this interval is a pure presentation one. */
  let prevIdle = false;
  /* The E4 bar, reported on its own — see `frameRateBelowBar`. Fed every rendered frame at every
     tier, auto or pinned, because the report is about the frames the user saw, not about the rule. */
  const rateBar = createFrameRateBar();
  /* Which slow frames were the FABRIC's — see `createForeignWorkLedger` in ./stepdown for the
     measurement that made this necessary. Long-task entries arrive asynchronously, after the task
     they describe, so a rendered frame waits in `judgeQueue` for ATTRIBUTION_LAG_MS before the
     step-down judge sees it: a step-down lands a quarter of a second later, and lands on evidence. */
  const foreignWork = createForeignWorkLedger();
  /* Each frame carries the tier it was rendered at: a frame measured before a tier change is not
     evidence about the tier that replaced it. */
  const judgeQueue: { from: number; to: number; raw: number; tier: QualityTier }[] = [];
  const ATTRIBUTION_LAG_MS = 250;
  let longTaskObserver: PerformanceObserver | null = null;
  try {
    if (typeof PerformanceObserver !== "undefined" && PerformanceObserver.supportedEntryTypes?.includes("longtask")) {
      longTaskObserver = new PerformanceObserver((list) => {
        /* determinism: long-task entry times are compared only with other frame-timing values to
           decide whether a slow frame is evidence for the adaptive tier rule; no value derived
           from them is rendered. */
        for (const e of list.getEntries()) foreignWork.noteLongTask(e.startTime, e.duration);
      });
      longTaskObserver.observe({ type: "longtask" });
    }
  } catch {
    longTaskObserver = null;
  }
  /* The other half of the adaptive rule — see `createStepUpPolicy`. The ceiling is the tier the
     session chose for ITSELF; a caller-pinned tier is not auto and is never moved. */
  const stepUp = createStepUpPolicy();
  if (decision.auto) stepUp.setCeiling(decision.tier);
  /** A step-up decided while the page was hidden, owed to the next frame (see onVisibility). */
  let pendingStepUp: QualityTier | null = null;
  /* WHEN a tier change may land — see `createGestureGate` in ./stepdown for the measurement. A
     step-down verdict is held here until the page is quiet, instead of rebuilding the post chain
     in the frame that presents a click or in the middle of a camera tween. */
  const gestureGate = createGestureGate();
  let heldStepDown: { reason: string; raw: number; since: number } | null = null;
  /* determinism: the ONE read of an input event's timestamp in this file. It decides only WHEN a
     held tier change may land (the gesture gate); it never reaches geometry, a material, a colour
     or an animation target. Funnelled through one helper so the gate reviews one read, not three. */
  const gestureStamp = (e: Event): number => e.timeStamp;
  const onGestureInput = (e: Event): void => gestureGate.noteInput(gestureStamp(e));
  const onGesturePointerDown = (e: Event): void => gestureGate.notePointer(true, gestureStamp(e));
  const onGesturePointerUp = (e: Event): void => gestureGate.notePointer(false, gestureStamp(e));
  /* WHEN an owed render may land while the reader works in a DOM panel — see ./panelInput for the
     measurement. The same event timestamp as the gesture gate (read through `gestureStamp`), and
     like it this decides only when a frame is drawn, never what is in it. */
  const panelInput = createPanelInputGate();
  const onPanelInput = (e: Event): void => {
    if (isFabricTarget(canvas, e.target)) panelInput.noteFabricInput(gestureStamp(e));
    else panelInput.noteForeignInput(gestureStamp(e));
  };
  const gestureTarget: Document | null = typeof document === "undefined" ? null : canvas.ownerDocument;
  if (gestureTarget !== null) {
    const o = { capture: true, passive: true } as const;
    gestureTarget.addEventListener("keydown", onGestureInput, o);
    gestureTarget.addEventListener("wheel", onGestureInput, o);
    gestureTarget.addEventListener("pointerdown", onGesturePointerDown, o);
    gestureTarget.addEventListener("pointerup", onGesturePointerUp, o);
    gestureTarget.addEventListener("pointercancel", onGesturePointerUp, o);
    gestureTarget.addEventListener("keydown", onPanelInput, o);
    gestureTarget.addEventListener("pointerdown", onPanelInput, o);
    gestureTarget.addEventListener("pointerup", onPanelInput, o);
  }
  /** Land a held step-down if the page is quiet. Returns true when it landed (the frame is over). */
  function landHeldStepDown(now: number): boolean {
    if (heldStepDown === null) return false;
    if (!tierIsAdaptive(decision)) {
      heldStepDown = null;
      return false;
    }
    /* A deferred tier change (see applyQuality) lands first: no frame is judged while it is owed. */
    if (deferredQuality !== null) return false;
    /* NEVER while the camera moves — a tween, a drag, a damped orbit's tail (C5 (b), 2026-09-23).
       A tier change re-warms the new chain, and the canvas presents nothing until that warm-up ends:
       landed mid-orbit on the contended host it froze the view for ~600 ms-1 s while the camera kept
       moving (measured twice: the grading's light/high orbit frame 407, and this wave's dark/high
       orbit-drag frame 550, where a drag that outlasted the gesture gate's 6 s backstop landed it).
       So camera motion is not one of the gate's bounded holds but an absolute one, checked BEFORE the
       gate: the verdict lands on the first frame the camera has been at rest for MOTION_HOLD_MS,
       which a gesture always reaches when it ends. The gate's own bounds (quiet input, a held
       pointer, `maxHoldMs`) still apply on top of it, unchanged. */
    if (cameraRig.isTweening() || now - lastCameraMotionAt < MOTION_HOLD_MS) return false;
    if (!gestureGate.mayLand(now, heldStepDown.since, false)) return false;
    const held = heldStepDown;
    heldStepDown = null;
    const next: QualityTier = decision.tier === "high" ? "balanced" : "low";
    stepUp.noteStepDown(decision.tier);
    stepDown.reset();
    rateBar.reset();
    tierLog = [
      ...tierLog,
      `stepped down to ${next}: ${held.reason}, last frame ${Math.round(held.raw)} ms, on this machine`,
    ];
    applyQuality({ tier: next, reasons: [...probeReasonsAt(probeDecision, next), ...tierLog], auto: true });
    emitStats(now);
    return true;
  }

  /**
   * The render loop.
   *
   * determinism: `now` is a clock — `requestAnimationFrame` hands this callback the same
   * DOMHighResTimeStamp `performance.now()` returns, which is why the determinism gate counts it
   * as a clock READ even though nothing here calls one. Everything derived from it (`fpsEma`,
   * `lastFrameMs`, `worstFrameMs`) is telemetry, and telemetry reaches the DOM in exactly one
   * place: the renderer disclosure in `app/StatusBar.tsx`, behind a click that no default view and
   * no capture state performs. Frame timing DOES steer one drawn thing: the quality tier. The
   * initial auto tier is chosen from the median of the first 60 frames, and it is NOT latched —
   * sustained slow frames step it down (`stepDown` → `landHeldStepDown` → `applyQuality`) and
   * a hidden page steps it back up (`onVisibility` → `pendingStepUp`). A tier change
   * changes the post chain and labels, so a clock-derived value can change what is
   * rendered. Nothing else is steered: `dt` advances animators that the capture harness waits out
   * via `converged`, and no timing value reaches geometry, colour or layout. Acceptance F6's
   * byte-identity therefore holds only AT A PINNED TIER, and that pin is enforced outside this file:
   * review/capture.mjs records every frame's tier and refuses (exit 3) any frame not rendered at
   * `high`. A caller-pinned tier (`quality` prop → `setQuality`) is not auto and is never moved.
   * If a frame-timing value ever starts deciding anything besides the tier, this note is false.
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
    foreignWork.noteFrame(now);

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

    const tweenBefore = cameraRig.isTweening();
    const cameraMoved = cameraRig.update(now);
    if (cameraMoved) lastCameraMotionAt = now;
    /* The camera's known arrival (see `tweenObservedFrom`): 0 on the landing frame. */
    const tweenAfter = cameraRig.isTweening();
    if (!tweenAfter) tweenObservedFrom = null;
    else if (tweenObservedFrom === null) tweenObservedFrom = now;
    cameraArrivalInMs =
      tweenBefore && !tweenAfter
        ? 0
        : tweenObservedFrom !== null
          ? Math.max(0, CAMERA_TWEEN_MS - (now - tweenObservedFrom))
          : null;
    /* "Moving" for the labels spans the damping tail: a pose change within MOTION_HOLD_MS, the
       same window the occlusion suspension uses, so a creeping orbit does not read as still. */
    labelsCameraMoving = now - lastCameraMotionAt < MOTION_HOLD_MS;
    /* Every animator runs every frame (no short-circuit). What they moved decides HOW the owed
       render is requested: an animated change is a change of content, a camera move only of view. */
    const emphasisMoved = animateEmphasis(dt);
    const fadesMoved = animateFades(dt);
    /* The tier cross-fade (see "tier cross-fade" above): driven on `raw`, the frame's real duration.
       The ease is the wall clock's, and FADE_MAX_STEP inside the driver is the per-frame bound that the
       64 ms `dt` clamp is not. It runs every frame, ahead of every early exit below, UNCONDITIONALLY
       (the driver is null while the hold waits and after the overlay is gone), and owes no render.
       While a warm-up runs (`compiled` false: a tier change, a theme change or new data re-links the
       programs) the canvas presents nothing new, and the driver HOLDS the fade: a fade that runs into
       a warm-up must still be up when the next presented frame lands, or that frame is the whole pop
       the fade exists to hide (R4-V1-4), and a tier change deferred through it (`deferredQuality`) is
       handed over from that value. */
    tierFade.frame(raw, reducedMotion, compiled);
    const flowMoved = flow.update(now, cameraRig.camera);

    if (emphasisMoved || fadesMoved || flowMoved) markDirty();
    else if (cameraMoved) requestFrame();
    /* The last presented frame mixed in a history (postfx.ts HISTORY_AA): once the camera stops, the
       frames that drain the weight to zero in stated steps are owed (`nextHistoryWeight`), so the
       frame a still view settles on is the plain chain's output. */
    if (historyInLastRender && !cameraMoved) requestFrame();
    /* The last render was taken with occlusion suspended for motion (see PostChain.setMotion): the
       still frame is owed as soon as the camera has held still for MOTION_HOLD_MS. */
    if (motionReducedRender && now - lastCameraMotionAt >= MOTION_HOLD_MS) markDirty();
    /* A held step-down lands on the first quiet frame, rendered or idle. */
    if (landHeldStepDown(now)) return;
    /* A tier change deferred through a warm-up (see applyQuality) lands on the first frame after that
       warm-up ended, when the copy it hands the running fade over to can be taken. */
    if (deferredQuality !== null && compiled) {
      applyQuality(deferredQuality);
      emitStats(now);
      return;
    }
    // See applyQuality: the first frame of a new post chain is atypical, so it is never the last
    // one rendered. Costs at most two frames, and only after an explicit tier change. The frame is
    // OWED, not new content (`requestFrame`): the tier cross-fade's hold reads a content change as
    // "the picture under the overlay moved on" and would otherwise be released by its own re-render.
    if (warmupFrames > 0) {
      warmupFrames -= 1;
      requestFrame();
    }

    if (!dirty) {
      stillFrames += 1;
      /* THE SETTLED LABEL PASS (acceptance F6). The first idle frame after the last render re-runs
         the label resolver once WITHOUT history — no hysteresis, no temporal hold, no staggered
         drops — over the camera that frame was rendered with. Measured before this existed: fresh
         loads of the same state kept or dropped access8's name 7:3, both meeting every settle
         condition, because the verdict depended on the frames that led to the still one. The labels
         are DOM, so no render is owed; and `converged` needs two still frames, so this always lands
         before a capture can be taken. */
      if (!labelsSettledPass && compiled && !cameraRig.isTweening()) recomputeLabels(true);
      /* An idle-after-idle interval is the display's presentation period and nothing else. */
      if (prevIdle && !suspended && !first) cadence.noteIdle(raw);
      prevIdle = true;
      /* A step-up is retried ONLY while nobody is looking at the fabric: it is decided when the
         page is hidden (see onVisibility) and lands on the first frame the browser runs after that.
         It used to be retried after 6 s of idle ON SCREEN, and that is a spontaneous change of image
         in front of a reader studying a still view: MEASURED (independent audit C5, 2026-09-22,
         Intel iGPU, DSF 2) about 11 s after two orbit gestures, with no input, the tier stepped
         back up to balanced, visibly changing ~3 % of the frame and stalling it for 550-730 ms.
         Bounded by `createStepUpPolicy`'s strike count, and announced like the step-down. */
      if (pendingStepUp !== null && decision.auto && heldStepDown === null && deferredQuality === null) {
        const up = pendingStepUp;
        pendingStepUp = null;
        tierLog = [
          ...tierLog,
          `stepped back up to ${up} while the page was hidden: the step-down measured a burst of ` +
            `interaction, not this machine's sustained rate; a second step-down from ${up} makes ` +
            `the lower tier this session's ceiling`,
        ];
        applyQuality({ tier: up, reasons: [...probeReasonsAt(probeDecision, up), ...tierLog], auto: true });
        emitStats(now);
        return;
      }
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
      /* The warm-up just ended: publish that on this frame rather than up to 500 ms later, so the
         stage's "Building the 3-D fabric" line does not outlive the work it describes. */
      lastStatsEmit = 0;
    }

    /* RESPONSIVENESS FIX, 2026-09-21 (acceptance E2/E3). A selection, highlight, trace or focus
       arrives from a React commit inside an input event, and the very next animation frame is the
       one that PRESENTS that event. Rendering the fabric in it put the composed render — outline
       passes re-running their full-scene depth pass for the new selection, SSAO, bloom — between
       the click and its paint: measured on the release build, the presentation delay of a finding
       select was 269-413 ms against 21-94 ms of handler time, with the rAF attributed here.

       So that one frame renders nothing: the page paints the panels' answer first, and the fabric
       follows one frame (~16 ms) later. `dirty` stays set, so the render is owed, not dropped. Never
       two yields in a row: a change arriving on every frame (a held arrow key) still renders at
       least every other frame rather than starving the canvas. */
    if (yieldToPage && !yieldedLastFrame) {
      yieldToPage = false;
      yieldedLastFrame = true;
      emitStats(now);
      return;
    }

    /* RESPONSIVENESS FIX, 2026-09-21 (E2/E3/E5, second pass). The one-frame yield above is not
       enough when the input is a BURST on a DOM panel — a typed word, a held ArrowDown in the grid,
       a palette command opening the Inspector: the owed render lands one frame later, which is
       where the next keystroke arrives, and LoAF put this callback on that keystroke's path at up
       to 326 ms. While discrete input is arriving somewhere other than the fabric, the owed render
       waits for a pause (bounded; see ./panelInput). `dirty` stays set, so it is owed, not
       dropped, and `converged` stays false until it lands. */
    if (panelInput.shouldDefer(now)) {
      emitStats(now);
      return;
    }
    yieldToPage = false;
    yieldedLastFrame = false;
    panelInput.rendered();
    prevIdle = false;

    /* A size delivered by `resize` lands HERE, with the render that repaints it, and therefore
       waits with that render while a panel is taking input: reallocating every render target of
       the post chain is most of what a resize costs (the Inspector opening shrinks the stage). The
       canvas is CSS-stretched meanwhile, which is the browser's own behaviour, never a blank. */
    if (pendingSize !== null) {
      const s = pendingSize;
      pendingSize = null;
      applySize(s.w, s.h);
    }

    recomputeLabels();

    /* The camera rig re-fits near/far to the fabric whenever the view moves far enough
       (camera.ts), and one pass in the chain caches that pair. Nothing else in the frame reads it,
       so the sync lives here, next to the render it has to be true for — and it is a no-op unless
       the projection actually moved. See `postfx.ts :: syncCamera`. */
    post.syncCamera();

    /* A drawing-buffer resize owed by a chain rebuild lands HERE, in the same animation frame as
       the composed render that repaints it — see applySize. */
    if (pendingPixelRatio !== null) {
      renderer.setPixelRatio(pendingPixelRatio);
      pendingPixelRatio = null;
      post.setSize(width, height);
    }

    /* Outline passes that will actually run in this render, counted BEFORE it: the render resets
       the flag that says so. See PostChain.outlinesUpdatingNextRender. */
    const outlinesThisFrame = post.outlinesUpdatingNextRender();

    /* Occlusion off while the camera moves, on for the first still frame (PostChain.setMotion; E4). */
    motionReducedRender = post.setMotion(now - lastCameraMotionAt < MOTION_HOLD_MS);
    if (motionReducedRender && now - lastCameraMotionAt >= MOTION_HOLD_MS) motionReducedRender = false;

    refreshRims();
    /* The history blend (postfx.ts HISTORY_AA): only for a frame whose content is the last presented
       frame's, weighted by how far the camera moved since that frame — and EASED from the weight
       that frame used, so neither turning it on nor draining it after a stop is a one-frame step
       (`nextHistoryWeight`; acceptance report 2026-09-23, C5 (a)). */
    const cameraStep = cameraStepSinceRenderPx();
    lastCameraStep = cameraStep;
    post.setHistoryWeight(
      nextHistoryWeight(post.historyWeightUsed(), cameraStep, contentVersion !== renderedContentVersion, cameraArrivalInMs, raw),
    );
    renderer.info.reset();
    if (!firstRendered) {
      firstRendered = true;
      mark("atlas:first-render", () => post.render(dt / 1000));
    } else {
      post.render(dt / 1000);
    }
    post.captureHistory();
    historyInLastRender = post.historyWeightUsed() > 0;
    renderedContentVersion = contentVersion;
    rememberRenderedCamera();
    releaseTierFade(now);

    /* A rebuild frame costs about 50 extra calls once (see DRAW_CALL_BUDGET); a REGRESSION costs
       them every frame. Two consecutive breaching rendered frames separates the two without
       hiding either — the dev console names every breaching frame, standing or not.

       The ceiling is the one that applies to THIS frame: the base budget plus a surcharge for each
       outline effect currently selecting something. A flat ceiling could only be right for one of
       those frames, and it was set for the idle one, which is why a traced frame breached it
       permanently and nobody could see it. */
    /* Budgeted on the outline passes that RAN, not on the selections that exist: the frame after a
       deselect, and the first frame of a rebuilt chain, run a full outline pass with an empty
       selection. Counting selections called that "117 calls with 0 outlines" — a breach by the
       accounting, not by the scene. */
    frameDrawCallBudget = drawCallBudgetFor(Math.max(activeOutlines(), outlinesThisFrame));
    if (renderer.info.render.calls > frameDrawCallBudget) {
      overBudgetFrames += 1;
      if (import.meta.env?.DEV === true) {
        // eslint-disable-next-line no-console
        console.error(
          `fabric3d: ${renderer.info.render.calls} draw calls exceeds the budget of ` +
            `${frameDrawCallBudget} for a frame with ${outlinesThisFrame} outline pass(es) run ` +
            `(consecutive breaching frames: ${overBudgetFrames})`,
        );
      }
      if (overBudgetFrames >= OVER_BUDGET_FRAMES) overBudget = true;
    } else {
      overBudgetFrames = 0;
      overBudget = false;
    }

    if (!suspended && !first) rateBar.push(raw);

    /* Adaptive step-down. Counted over RENDERED frames only: idle frames cost nothing and would
       otherwise dilute the average into never tripping. The step is announced, not silent. */
    if (tierIsAdaptive(decision) && heldStepDown === null) {
      // Judged on the TRUE delta, and announced with it: a clamped 64 in this sentence would tell
      // the reader the step-down happened over a 64 ms frame when it happened over an 800 ms one.
      /* Judged ATTRIBUTION_LAG_MS late, and only on frames the page's own long work did not
         produce — see `createForeignWorkLedger`. A frame the ledger excuses is still in `raw`,
         `fpsEma` and `worstFrameMs` above; it is only not blamed on the renderer. */
      /* ...and not while a deferred tier change is owed (see applyQuality): those frames are the tier it
         is leaving, and a verdict on them would land on the tier it arrives at. */
      if (!suspended && deferredQuality === null) judgeQueue.push({ from: now - raw, to: now, raw, tier: decision.tier });
      let verdict: ReturnType<typeof stepDown.push> | null = null;
      while (judgeQueue.length > 0 && (judgeQueue[0]?.to ?? now) <= now - ATTRIBUTION_LAG_MS) {
        const f = judgeQueue.shift();
        if (f === undefined) break;
        if (f.tier !== decision.tier || !frameIsFabricEvidence(foreignWork, f.from, f.to)) continue;
        verdict = stepDown.push(f.raw, cadence.periodMs());
        if (verdict.step) break;
      }
      foreignWork.prune(now - 5000);
      if (verdict?.step) {
        /* HELD, not applied: the rebuild lands on the first quiet frame (landHeldStepDown), never
           inside an interaction's presentation or a camera tween. The judge is not fed while a
           verdict is held, so the verdict cannot be re-issued or overwritten meanwhile. */
        judgeQueue.length = 0;
        heldStepDown = { reason: verdict.reason, raw, since: now };
        if (landHeldStepDown(now)) return;
      }
    }

    dirty = false;
    stillFrames = 0;
    if (labelsNeedFrame) {
      labelsNeedFrame = false;
      dirty = true;
    }
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
      // A frame rendered with occlusion suspended for motion is not the frame the scene settles on.
      // Nor is one whose DOM label set is about to change (reportLabelsConverging).
      dirty: dirty || motionReducedRender || domLabelsConverging || historyInLastRender,
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
      qualityReasons: [
        ...displayLimitReasons(),
        ...(rateBar.below() ? [rateBar.reason()] : []),
        ...(motionReducedRender
          ? ["ambient occlusion is suspended while the camera moves and restored on the first still frame"]
          : []),
        ...decision.reasons,
        ...(SHADOW_MAP_IN_USE ? [] : [SHADOW_MAP_REASON]),
      ],
      qualityAuto: decision.auto,
      overBudget,
      drawCallBudget: frameDrawCallBudget,
      activeOutlines: activeOutlines(),
      missingTokens: graph.tokens.missing,
      undrawnHops: flow.undrawnHops(),
      labelsShown: labelsPlaced ?? labelsShown,
      labelsTotal: graph.order.length,
      labelsBehindChassis,
      warmupStage,
      programsLinked,
      programsTotal,
      warmupTimedOut,
      framesTimed,
      frameRateBelowBar: rateBar.below(),
      historyWeight: post.historyWeightUsed(),
      historyCameraStepPx: Number.isFinite(lastCameraStep) ? Math.round(lastCameraStep * 10000) / 10000 : null,
    };
  }

  /** The display-limit sentence, while the measured cadence actually rescales the step-down bars. */
  function displayLimitReasons(): string[] {
    const period = cadence.periodMs();
    if (period === null || !effectiveBars(STEP_DOWN_DEFAULTS, period).displayLimited) return [];
    return [displayLimitReason(period)];
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
    /* The page may come back on a different display (or out of a power governor): re-measure. */
    cadence.reset();
    prevIdle = false;
    /* The one moment a stepped-down tier may be retried: the reader has left the page, so the
       swap cannot land inside a gesture or change a still view under their eyes. It lands on the
       next frame the browser runs (behind the tier cross-fade). */
    if (typeof document !== "undefined" && document.visibilityState === "hidden" && decision.auto && heldStepDown === null) {
      pendingStepUp = stepUp.poll(decision.tier, Number.POSITIVE_INFINITY);
    }
    markDirty();
  };
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibility);
  }

  /* A camera change changes the view, not the content (see `contentVersion`). */
  const onCameraChange = (): void => {
    requestFrame();
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
      const signature = sceneDataSignature(devices, links, nextLayout);
      if (signature === graph.signature) {
        // Same topology: the GPU buffers are still correct and only the per-instance colours can
        // have moved. Rebuilding here would drop every material and recompile every shader for a
        // band change, which is the kind of thing that turns a filter into a stutter.
        for (const s of graph.order) {
          const next = devices.find((d) => d.id === s.id);
          if (next === undefined) continue;
          s.device = next;
          if (!s.ghost && s.group.body !== null) {
            s.group.body.setColorAt(s.slot, bandTint(next, graph.tokens, _colour));
          }
          if (!s.ghost && s.group.led !== null) {
            s.group.led.setColorAt(s.slot, bandEmissive(next, graph.tokens, _colour));
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

      sourceDevices = devices;
      sourceLinks = links;
      sourceLayout = nextLayout;
      rebuildGraph(true);
    },

    setSelection(deviceId: string | null, linkId: string | null): void {
      if (applySelection(deviceId, linkId)) yieldToPage = true;
    },

    acknowledgeSelection(deviceId: string | null, linkId: string | null): void {
      /* No yield: see FabricSceneEx.acknowledgeSelection. */
      applySelection(deviceId, linkId);
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
      yieldToPage = true;
    },

    setTrace(next: Trace | null, hop: number | null): void {
      trace = next;
      activeHop = hop;
      flow.setTrace(next, activeHop, traceSource);
      post.setBloomObjects([...graph.emissiveObjects, ...flow.emissiveObjects()]);
      recomputeEmphasis();
      markEmphasisDirty(emphasis);
      /* The drawn path's sphere, or — when no cable was stitched (a flow delivered at its first
         hop, or every hop pair undrawn) — the hop DEVICES themselves. The trace used to reframe
         only when a path was drawn, so a one-device trace (MEASURED, C5 audit: delivered at core1,
         hop 0) was left on the overview with core1 flush to the canvas top, its "delivered here"
         chip on its own chassis and core2's name under the toolbar. */
      const s = flow.pathSphere();
      if (s !== null) {
        _world.set(s.center[0], s.center[1], s.center[2]);
        cameraRig.moveTo(
          frameSphereFromCurrentView(cameraRig.camera, cameraRig.controls.target, _world, s.radius, 1.35),
        );
      } else if (next !== null) {
        // One distinct hop device frames exactly as focusing it would (the device and the
        // neighbourhood it sits in); several with no stitched cable frame their union.
        const hosts = new Set(next.hops.map((h) => h.host));
        const only = hosts.size === 1 ? [...hosts][0] : undefined;
        const pose = only !== undefined ? focusFramingFor(only) : null;
        const hs = pose === null ? hopDeviceSphere(next) : null;
        if (pose !== null) {
          cameraRig.moveTo(pose);
        } else if (hs !== null) {
          _world.set(hs.center[0], hs.center[1], hs.center[2]);
          cameraRig.moveTo(
            frameSphereFromCurrentView(cameraRig.camera, cameraRig.controls.target, _world, hs.radius, 1.35),
          );
        }
      }
      markDirty();
      yieldToPage = true;
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
      // Wheel-zoom toward the subject from here on (camera.ts, zoom anchor); cleared by the next move.
      const focused = graph.slots.get(deviceId);
      if (focused !== undefined) {
        /* The device's own bounding radius sets the dolly floor, so a wheel-in can reach the
           chassis detail rather than stopping at a fraction of the neighbourhood framing. */
        cameraRig.setZoomAnchor(
          [focused.centre[0], focused.centre[1], focused.centre[2]],
          Math.hypot(focused.half[0], focused.half[1], focused.half[2]),
        );
      }
      markDirty();
      yieldToPage = true;
    },

    resetCamera(resetOpts?: { immediate?: boolean }): void {
      cameraRig.home(resetOpts);
      markDirty();
    },

    orbitBy(dxPx: number, dyPx: number): void {
      cameraRig.orbitBy(dxPx, dyPx);
      markDirty();
    },

    panBy(dxPx: number, dyPx: number): void {
      cameraRig.panBy(dxPx, dyPx);
      markDirty();
    },

    setTheme(next: "dark" | "light"): void {
      if (next === theme) return;
      applyTheme(next);
    },

    setReducedMotion(reduced: boolean): void {
      if (reduced === reducedMotion) return;
      reducedMotion = reduced;
      cameraRig.setReducedMotion(reduced);
      flow.setReducedMotion(reduced);
      markDirty();
    },

    setQuality(q: QualityTier): void {
      /* A caller's tier is a PIN, including the tier already in force (quality.ts `pinQuality`):
         a pinned tier is outside the adaptive step-down, and `stats().qualityAuto` reads false. */
      /* The caller's latest tier wins over one still deferred through a warm-up (see applyQuality). */
      deferredQuality = null;
      const pin = pinQuality(decision, q);
      if (pin.decision === decision) return; /* already pinned at q */
      tierLog = [];
      if (pin.rebuild) {
        applyQuality(pin.decision);
        return;
      }
      /* Same tier: pin it in place. Nothing drawn changes, so there is no rebuild and no warm-up —
         the path that freezes the view if a tier change lands mid-motion is not entered. Whatever
         the adaptive rule had in flight is dropped with the auto flag. */
      decision = pin.decision;
      heldStepDown = null;
      pendingStepUp = null;
      judgeQueue.length = 0;
      stepDown.reset();
    },

    resize(w: number, h: number): void {
      /* Before the first render there is nothing to stretch, and the warm-up sizes its targets
         from these: apply at once. After it, the size lands with the next composed render. */
      if (!firstRendered) {
        pendingSize = null;
        applySize(w, h);
        return;
      }
      pendingSize = { w, h };
      markDirty();
    },

    pick(clientX: number, clientY: number): PickResult | null {
      return interaction.pick(clientX, clientY);
    },

    reportLabelsShown(n: number): void {
      labelsPlaced = Math.max(0, Math.min(graph.order.length, Math.round(n)));
    },

    reportLabelsConverging(b: boolean): void {
      domLabelsConverging = b;
    },

    labelsSettled(): boolean {
      return labelsSettledPass && !dirty && !domLabelsConverging;
    },

    chassisScreenBox(deviceId: string): { x0: number; y0: number; x1: number; y1: number } | null {
      const s = graph.slots.get(deviceId);
      if (s === undefined) return null;
      const cam = cameraRig.camera;
      let x0 = Infinity;
      let y0 = Infinity;
      let x1 = -Infinity;
      let y1 = -Infinity;
      for (let k = 0; k < 8; k += 1) {
        _world.set(
          s.centre[0] + (k & 1 ? s.half[0] : -s.half[0]),
          s.centre[1] + (k & 2 ? s.half[1] : -s.half[1]),
          s.centre[2] + (k & 4 ? s.half[2] : -s.half[2]),
        );
        _world.project(cam);
        if (!(_world.z > -1 && _world.z < 1)) return null;
        const sx = (_world.x * 0.5 + 0.5) * width;
        const sy = (-_world.y * 0.5 + 0.5) * height;
        x0 = Math.min(x0, sx);
        y0 = Math.min(y0, sy);
        x1 = Math.max(x1, sx);
        y1 = Math.max(y1, sy);
      }
      // The same CSS stretch `project()` applies while a resize is owed.
      const fx = pendingSize === null ? 1 : Math.max(1, Math.round(pendingSize.w)) / width;
      const fy = pendingSize === null ? 1 : Math.max(1, Math.round(pendingSize.h)) / height;
      return { x0: x0 * fx, y0: y0 * fy, x1: x1 * fx, y1: y1 * fy };
    },

    project(deviceId: string): { x: number; y: number; visible: boolean } | null {
      const p = projectLabelAnchor(deviceId);
      if (p === null) return null;
      /* While a resize is owed (see `resize`), the canvas shows the LAST composed frame stretched
         by CSS to the new box. A DOM label must sit on the device as it is drawn, so it is scaled
         by the same stretch; otherwise, measured on the Inspector opening, every label sat on the
         wrong chassis for the frames the resize waited. */
      const sx = pendingSize === null ? 1 : Math.max(1, Math.round(pendingSize.w)) / width;
      const sy = pendingSize === null ? 1 : Math.max(1, Math.round(pendingSize.h)) / height;
      return { x: p.x * sx, y: p.y * sy, visible: p.visible && labelAllowed(deviceId) };
    },

    stats(): SceneStatsEx {
      return snapshot();
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(raf);
      tierFade.dispose();
      if (tierFadeBackstop !== null) clearTimeout(tierFadeBackstop);
      tierFadeBackstop = null;
      deferredQuality = null;
      longTaskObserver?.disconnect();
      if (gestureTarget !== null) {
        const o = { capture: true } as const;
        gestureTarget.removeEventListener("keydown", onGestureInput, o);
        gestureTarget.removeEventListener("wheel", onGestureInput, o);
        gestureTarget.removeEventListener("pointerdown", onGesturePointerDown, o);
        gestureTarget.removeEventListener("pointerup", onGesturePointerUp, o);
        gestureTarget.removeEventListener("pointercancel", onGesturePointerUp, o);
        gestureTarget.removeEventListener("keydown", onPanelInput, o);
        gestureTarget.removeEventListener("pointerdown", onPanelInput, o);
        gestureTarget.removeEventListener("pointerup", onPanelInput, o);
      }
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

  /** A sphere over the trace's hop devices, sized like a device focus so one hop is not a close-up. */
  function hopDeviceSphere(t: Trace): { center: [number, number, number]; radius: number } | null {
    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    let own = 0;
    for (const hop of t.hops) {
      const s = graph.slots.get(hop.host);
      if (s === undefined) continue;
      minX = Math.min(minX, s.centre[0] - s.half[0]);
      maxX = Math.max(maxX, s.centre[0] + s.half[0]);
      minY = Math.min(minY, s.centre[1] - s.half[1]);
      maxY = Math.max(maxY, s.centre[1] + s.half[1]);
      minZ = Math.min(minZ, s.centre[2] - s.half[2]);
      maxZ = Math.max(maxZ, s.centre[2] + s.half[2]);
      own = Math.max(own, Math.hypot(s.half[0], s.half[1], s.half[2]));
    }
    if (!Number.isFinite(minX)) return null;
    return {
      center: [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2],
      radius: Math.max(Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2, own * 3),
    };
  }

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
    /* The cap is a share of the FABRIC, not a multiple of the device. It used to be own * 4.6, and
       for a small chassis that is smaller than the distance to any neighbour: MEASURED (independent
       audit C5, 2026-09-22) focusDevice('AP-floor1') framed the AP alone at the lower centre with
       2 of 26 labels and only a fan of cable stubs — no neighbour on screen — and core1's framing
       cut its access layer off at the bottom while leaving the top third empty. The contract is
       "frame one device and its neighbours", so the neighbourhood is framed whole up to a bounded
       share of the fabric; only a hub whose neighbourhood IS most of the fabric is capped (then the
       bias below keeps the subject in frame and leans the view into its neighbours). */
    const fabricRadius = layout.framing.boundingSphere?.radius ?? radiusOf(layout);
    const cap = Math.max(own * 4.6, fabricRadius * FOCUS_MAX_FABRIC_SHARE);
    const radius = Math.min(Math.max(neighbourhood, own * 1.9), cap);
    /* Centred on the DEVICE, then biased toward its neighbourhood by at most FOCUS_MAX_BIAS of the framed
       radius — so the subject always stays well inside the frame, but a device at the edge of the
       fabric no longer frames empty space. MEASURED (C5 audit): focusing core1, whose every
       neighbour is below it, put core1 dead centre and left the upper ~45 % of the stage void. A
       pure midpoint is still wrong for a hub (see the cap above), which is why the bias is bounded. */
    const bx = (minX + maxX) / 2 - slot.centre[0];
    const by = (minY + maxY) / 2 - slot.centre[1];
    const bz = (minZ + maxZ) / 2 - slot.centre[2];
    const bLen = Math.hypot(bx, by, bz);
    const bk = bLen > 1e-6 ? Math.min(1, (radius * FOCUS_MAX_BIAS) / bLen) : 0;
    _world.set(slot.centre[0] + bx * bk, slot.centre[1] + by * bk, slot.centre[2] + bz * bk);
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

/** Largest share of the fabric's bounding radius a device focus may frame (see focusFramingFor).
 *
 *  0.4, was 0.6, with the bias below 0.5, was 0.7. MEASURED (audit A5, 1920x1080, canvas 1160x962):
 *  at 0.6 x the 1.4 margin a focus framed ~84 % of the fabric, i.e. the overview again. Double-click
 *  or Enter on access13 grew its chassis 51 -> 52 px and moved it 43 px; core1 53 px, dist1 not at
 *  all. An access switch's neighbours are core1 at the top and AP-floor1 at the bottom, so "frame
 *  the device and ALL its neighbours" is the whole fabric for most of this snapshot. The declared
 *  bar now: the subject grows to >= 1.4x its overview width and sits near the centre, while its
 *  neighbourhood stays on screen (the C5 finding that the AP was once framed ALONE still holds).
 *  Measured after: access13 51 -> 77 px, 13 px off centre, 21 of 26 devices on screen; core1
 *  55 -> 80 px, 15 on screen; AP-floor1 22 -> 35 px, 12 on screen; podacc2 54 -> 81 px, 8 on
 *  screen; dist1 53 -> 80 px. 0.32 / 0.35 zoomed further (~1.9x) but left AP-floor1 and podacc2
 *  with ONE other device in frame, which is the C5 regression. */
const FOCUS_MAX_FABRIC_SHARE = 0.4;
/** Largest share of the framed radius the focus centre may lean from the device toward its
 *  neighbourhood (see focusFramingFor). */
const FOCUS_MAX_BIAS = 0.5;

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
