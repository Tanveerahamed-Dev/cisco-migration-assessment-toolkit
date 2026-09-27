/**
 * postfx.ts — the post chain, in the one order that is defensible, plus the knobs to prove it.
 *
 * Order rationale (design-brief.md §4.6), restated because the order IS the design:
 *   RenderPass            the scene, into a HalfFloat linear buffer
 *   NormalPass            a clean view-space normal buffer, before anything adds glow
 *   DepthDownsamplingPass half-res normal+depth for the SSAO's depth-aware upsampling
 *   EffectPass(SSAO)      occlusion computed while the depth buffer is still pristine
 *   EffectPass(bloom, outlines)
 *                         bloom thresholds HDR LINEAR luminance, which is the only condition under
 *                         which `luminanceThreshold: 1.0` means "this surface is emitting" rather
 *                         than "this surface is bright". Outlines are merged into the same shader
 *                         by EffectPass, so selection costs one pass, not three.
 *   EffectPass(tone)      tone mapping once, on the whole image, in a pass of its OWN
 *   EffectPass(SMAA, dither)
 *                         anti-aliasing on the display-referred image, then half an LSB of
 *                         deterministic dither so the 8-bit write does not band the stage gradient.
 *
 * The SMAA-after-tone-mapping placement was flagged INFERRED in the brief. It is now SETTLED, by
 * measurement, and the last two passes are split because that is the only way to express it — see
 * the comment above `tonePass` and docs/render-decisions.md. The knob that used to advertise the
 * A/B (`smaaAfterToneMapping`) has been removed: it was never reachable from `SceneOptions`, and
 * once measured it could not have changed a pixel anyway.
 *
 * Nothing here is atmosphere. There is no vignette, no chromatic aberration, no film grain and no
 * god rays, and bloom is layer-bound: a glow in this application means "this element is emitting",
 * which is information.
 */
import {
  BlendFunction,
  DepthDownsamplingPass,
  EdgeDetectionMode,
  Effect,
  EffectComposer,
  EffectPass,
  KernelSize,
  NormalPass,
  OutlineEffect,
  Pass,
  RenderPass,
  SMAAEffect,
  SSAOEffect,
  SelectiveBloomEffect,
  ToneMappingEffect,
  ToneMappingMode,
} from "postprocessing";
import {
  DataTexture,
  FramebufferTexture,
  HalfFloatType,
  NearestFilter,
  NoColorSpace,
  RGBAFormat,
  RepeatWrapping,
  SRGBColorSpace,
  Uniform,
  UnsignedByteType,
  Vector2,
  type Camera,
  type Object3D,
  type Scene,
  type ShaderMaterial,
  type WebGLRenderer,
} from "three";
import { SELECTION_LAYERS, assertLayerRegistry } from "./layers";
import type { TokenPalette } from "./materials";
import type { QualityProfile } from "./quality";

export interface PostChainOptions {
  renderer: WebGLRenderer;
  scene: Scene;
  camera: Camera;
  tokens: TokenPalette;
  profile: QualityProfile;
  /**
   * NEUTRAL for the export path, AgX for the live scene. AgX has the softest shoulder and is what
   * keeps a saturated critical red from blowing to orange-white as emissive intensity climbs;
   * NEUTRAL leaves severity hues unshifted, which is what a report needs. ACES_FILMIC is used
   * nowhere: it shifts colour the most, and this is an evidence tool, not a film.
   */
  toneMapping?: "agx" | "neutral";
}

export interface PostChain {
  composer: EffectComposer;
  /** Objects whose emissive surfaces are allowed to bloom. Nothing else glows, ever. */
  bloomSelection: Set<Object3D>;
  setBloomObjects(objects: readonly Object3D[]): void;
  setSelectionOutline(objects: readonly Object3D[]): void;
  setBlockedOutline(objects: readonly Object3D[]): void;
  /**
   * How many OutlineEffects will run their full-scene depth + mask pass in the NEXT render.
   *
   * Not the same as "how many have a selection". postprocessing's OutlineEffect.update() runs when
   * `forceUpdate || selection.size > 0` and then sets `forceUpdate = selection.size > 0` — so the
   * frame AFTER a selection is cleared still pays the whole pass once (to clear the mask), and so
   * does the first frame of a freshly constructed effect (`forceUpdate = true` in its
   * constructor). Budgeting those frames by selection size alone logged "117 draw calls exceeds
   * the budget of 88 ... 0 outline effect(s) active" on every deselect. Read BEFORE rendering;
   * the render resets the flag.
   */
  outlinesUpdatingNextRender(): number;
  setSize(width: number, height: number): void;
  /**
   * Suspend the ambient-occlusion stage (normal pass, depth downsampling, SSAO) while the camera is
   * moving, and restore it when it stops. Returns true when this chain HAS such a stage, i.e. when a
   * frame rendered in motion differs from the still frame and a still frame is therefore owed.
   *
   * Why (2026-09-22 critic, E4 blocker): at `high`, 1160x962, focus flights and orbit drags rendered
   * at a 52-55 fps median with a 33.3 ms p95 — whole vsync frames missed — and SSAO's three passes
   * (a full-scene normal render, a depth downsample and 16x7 occlusion sampling) are the costliest
   * stage of the chain. Occlusion is a static-shape cue: in motion it cannot be read, so it is paid
   * for only on the frames a reader can study. The first still frame renders the full chain, so every
   * capture, and every frame anyone looks at, is unchanged.
   */
  setMotion(inMotion: boolean): boolean;
  /**
   * Re-read the camera's near/far into the passes that cached them. Call once per frame; it is a
   * no-op unless the projection actually moved. See `syncCamera` in the implementation for the
   * measurement that made this necessary.
   */
  syncCamera(): void;
  retint(tokens: TokenPalette): void;
  /** The invariant a unit test pins: pass classes in order, with the effects inside each pass. */
  describe(): string[];
  /**
   * The history weight the NEXT render may use (see `nextHistoryWeight`), 0..HISTORY_AA.weight. It
   * is used only when the chain holds a valid previous frame; anything the chain itself changes (a
   * size, the motion-suspended occlusion stage, a retint) invalidates that frame, and the render
   * after it is plain. Consumed by one render: an unset weight is 0.
   */
  setHistoryWeight(weight: number): void;
  /** The weight the LAST render actually used — 0 means that frame was the plain chain's output. */
  historyWeightUsed(): number;
  /**
   * Keep the frame just presented as the history for the next render. Called by the scene after
   * its presenting render ONLY (never after a warm-up or recording render, which do not reach the
   * canvas), so the history is always a frame the reader saw.
   */
  captureHistory(): void;
  render(deltaSeconds: number): void;
  dispose(): void;
}

/* ── TEMPORAL STABILITY UNDER A CREEPING CAMERA (acceptance C5 "edge sparkle", 2026-09-23) ────────
 *
 * WHAT FLICKERS, CLASSIFIED rather than assumed. `review/capture-motion.mjs` now classifies every
 * flip-flopping pixel by the image around it. Release build, Intel iGPU / ANGLE D3D11, 760x790, the
 * two orbit sequences at dark/high and light/low: 293/37, 651/16, 329/111 and 696/39
 * (thin-stroke / silhouette) of 330, 667, 440 and 735 flipping pixels — 90 % of them thin strokes
 * (cables, curbs, faceplate strips), the rest silhouettes; ZERO specular highlights and ZERO flat
 * (shading or ambient-occlusion) pixels. So it is not a shading problem (specular anti-aliasing or a
 * stable SSAO would change nothing), and the independent attribution already in the harness holds:
 * with SMAA's blend weights cleared the same sequences flip 7-65 px. SMAA decides per frame, from
 * the frame alone, where a 1-3 px feature's edges are and how to blend them; while the damped orbit
 * creeps the feature a fraction of a pixel per frame, those decisions toggle, and a pixel goes
 * up-down-up by 12-100+ levels.
 *
 * WHAT DID NOT CLOSE IT, measured by earlier waves (docs/render-decisions.md): 4x MSAA through the
 * composer (worse for these strokes, and off for that reason — see `multisampling` above); every
 * SMAA preset (347/350 px); diagonal detection off (259 px); diagonal off plus a stroke mask
 * (107-194 px); 2x supersampling (75-125 px, at four times the fill).
 *
 * WHAT DOES: the chain's final output is blended with the frame the reader saw last, ONLY while the
 * camera creeps (the reprojection-free half of a temporal anti-aliaser — at under a pixel per frame
 * the previous frame is already aligned to within that pixel, so no motion vectors are needed). An
 * exponential history of weight w turns a pixel that toggles by D every frame into one that moves
 * by D(1-w)/(1+w): at w = 0.75, a seventh. It is OFF — the output is the plain chain's, bit for bit
 * — whenever the camera is still (so every settled frame, and therefore every F6 capture, is
 * unchanged), whenever the camera moves faster than a pixel a frame (where a history would trail),
 * and on any frame where something other than the camera changed (a selection, an ease, a tier, a
 * size, the occlusion stage switching for motion): a history is only ever a previous picture of the
 * SAME content. A frame drawn with a history is always followed by a plain one before the scene
 * reports `converged` (scene.ts).
 *
 * THE WEIGHT ITSELF EASES (acceptance report 2026-09-23, C5 (a)). Ramping the weight over camera
 * SPEED was not enough: a speed ramp says nothing about a camera that STOPS. Measured by the
 * grading, dark reset-fly, a contended host: a 0.465 px creep after a 166.6 ms gap was blended at
 * 0.75, the next frame was still and therefore plain, and 46,569 px changed with nothing moving —
 * the whole history's lag landing in one frame. So `nextHistoryWeight` moves the weight by at most
 * `maxStepPerFrame` per presented frame, both on the way in and on a still frame's way out (the drain
 * after an unannounced stop, 6 frames, over before the occlusion stage returns). A stop known in
 * advance — a tween's landing — is ramped out BEFORE it (`arrivalRampMs`, stretched to the frames
 * the current frame rate leaves), and a frame the camera moved on may drop to the ceiling its motion
 * sets (a history at or past a pixel would trail; one held up to a known landing would be that lag
 * again): the catch-up then rides on a frame whose picture is moving anyway. The one absolute is a
 * content change: 0 at once, since mixing two different pictures is wrong, not merely visible. */
export const HISTORY_AA = Object.freeze({
  /** Weight of the previous frame at full strength. */
  weight: 0.75,
  /** Camera step (drawing-buffer px per rendered frame) at which the weight reaches full strength. */
  fullFromPx: 0.02,
  /** ...holds it up to here... */
  fullToPx: 0.5,
  /** ...and is back to zero here and above: a history of a frame this far away would trail. */
  offAtPx: 1,
  /** The most the weight may change between two presented frames. */
  maxStepPerFrame: 0.125,
  /** A camera arrival known in advance (a tween) ramps the weight to zero over at least this long. */
  arrivalRampMs: 150,
  /**
   * A step below this (drawing-buffer px) is float noise, not motion: the camera is still. MEASURED
   * (engine gate, 2026-09-27): OrbitControls re-derives the pose through spherical coordinates on
   * every update(), and at some poses (a headed window at a forced 1.261 scale with the page at
   * devicePixelRatio 0.9999999908) that moves the camera by ~2.3e-13 px every frame while the rig and
   * OrbitControls both call it still. Weighted as a creep, it pinned the history at 8.6e-12 forever,
   * so the scene owed a plain frame on every frame and never reported `converged`. The floor is 4+
   * orders above that noise and 4 orders below `fullFromPx`, and the weight it withholds (3.75e-5)
   * cannot move an 8-bit channel.
   */
  stillBelowPx: 1e-6,
});

/** The history weight for a camera that moved `stepPx` drawing-buffer pixels since the last render. */
export function historyWeightFor(stepPx: number): number {
  const h = HISTORY_AA;
  if (!(stepPx >= h.stillBelowPx) || stepPx >= h.offAtPx) return 0;
  if (stepPx < h.fullFromPx) return h.weight * (stepPx / h.fullFromPx);
  if (stepPx <= h.fullToPx) return h.weight;
  return h.weight * ((h.offAtPx - stepPx) / (h.offAtPx - h.fullToPx));
}

/**
 * The weight the NEXT presented frame uses.
 *
 * `previous` is the weight the last presented frame used (`historyWeightUsed`), `stepPx` the camera's
 * step since it, `contentChanged` whether anything but the camera changed since it, `arrivalInMs`
 * how long until the camera is known to come to rest (0 on a tween's landing frame, null when no
 * arrival is known) and `frameMs` the last frame interval.
 */
export function nextHistoryWeight(
  previous: number,
  stepPx: number,
  contentChanged: boolean,
  arrivalInMs: number | null,
  frameMs: number,
): number {
  const h = HISTORY_AA;
  /* A history is only ever a previous picture of the SAME content, and never one a pixel or more
     away: those two are absolute, whatever the weight was. */
  if (contentChanged || !(stepPx >= 0) || stepPx >= h.offAtPx) return 0;
  /* Float noise is a still camera (HISTORY_AA.stillBelowPx): it drains like one, and never carries
     the moving-frame drop below. */
  if (stepPx < h.stillBelowPx) stepPx = 0;
  const prev = previous > 0 ? Math.min(h.weight, previous) : 0;
  /* What the camera's motion asks for: the step rule, and, when the camera's arrival at rest is
     known in advance, a ramp to zero over the frames before it — at least `arrivalRampMs`, and at
     least as many frames at the current frame rate as the weight needs to get there in steps. */
  let arrival: number = h.weight;
  if (arrivalInMs !== null) {
    const horizon = Math.max(h.arrivalRampMs, (h.weight / h.maxStepPerFrame) * (frameMs > 0 ? frameMs : 0));
    arrival = h.weight * Math.min(1, Math.max(0, arrivalInMs / horizon));
  }
  const target = Math.min(historyWeightFor(stepPx), arrival);
  const eased = Math.min(prev + h.maxStepPerFrame, Math.max(prev - h.maxStepPerFrame, target));
  if (!(stepPx > 0)) return eased;
  /* A frame the camera MOVED on may fall below the eased value, to the ceiling its own motion sets:
     a history kept above the trail ramp would ghost, and one kept up to a known arrival would be a
     lag landing on the still frame after it — the reported pop. The catch-up then rides on a frame
     whose picture is moving anyway, never on a still one. */
  const trail = stepPx <= h.fullToPx ? h.weight : historyWeightFor(stepPx);
  return Math.min(eased, trail, arrival);
}

/**
 * The blend with the previous frame, as the LAST effect before the output dither in the final pass.
 * The history is a copy of the canvas, i.e. DISPLAY-encoded 8-bit values, so it is decoded to linear
 * here before it is mixed with this frame's linear colour; the pass's own encode then writes the
 * result. At weight 0 the effect returns its input untouched, so the plain chain's output is
 * reproduced exactly.
 */
class HistoryEffect extends Effect {
  readonly history: Uniform<FramebufferTexture>;
  readonly weight: Uniform<number>;
  constructor(texture: FramebufferTexture, historyIsEncoded: boolean) {
    const history = new Uniform(texture);
    const weight = new Uniform(0);
    super(
      "HistoryEffect",
      `uniform sampler2D atlasHistory;
      uniform float atlasHistoryWeight;
      vec3 atlasHistoryDecode(const in vec3 c) {
        vec3 v = max(c, vec3(0.0));
        return mix(v / 12.92, pow((v + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), v));
      }
      void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
        if (atlasHistoryWeight <= 0.0) {
          outputColor = inputColor;
          return;
        }
        vec3 previous = texture2D(atlasHistory, uv).rgb;
        ${historyIsEncoded ? "previous = atlasHistoryDecode(previous);" : ""}
        outputColor = vec4(mix(inputColor.rgb, previous, atlasHistoryWeight), inputColor.a);
      }`,
      {
        blendFunction: BlendFunction.NORMAL,
        uniforms: new Map<string, Uniform>([
          ["atlasHistory", history],
          ["atlasHistoryWeight", weight],
        ]),
      },
    );
    this.history = history;
    this.weight = weight;
  }
}

function createHistoryTexture(width: number, height: number): FramebufferTexture {
  const t = new FramebufferTexture(Math.max(1, width), Math.max(1, height));
  t.minFilter = NearestFilter;
  t.magFilter = NearestFilter;
  /* The bytes are display values and are decoded in the shader; a colour-managed texture would be
     decoded a second time on sampling. */
  t.colorSpace = NoColorSpace;
  t.generateMipmaps = false;
  return t;
}

/**
 * Occlusion proximity window, in WORLD units, converted below against the camera's depth range.
 *
 * A sample occludes the shaded point when the two are within this distance in depth; past
 * `+ FALLOFF` it contributes nothing. Sized for this fabric's geometry — a 4-8 unit chassis
 * standing ~2 units above its deck — so a chassis is occluded by its own deck and its own bezel,
 * and never by a tier 64 units away.
 */
const AO_PROXIMITY_WORLD = 3;
const AO_PROXIMITY_FALLOFF_WORLD = 9;

/**
 * The SSAO sampling radius as a UNIFORM, not a `#define` baked from the stage height.
 *
 * postprocessing's `SSAOMaterial.updateRadius` writes `RADIUS = r * resolution.height` (and its
 * square) into `defines` with 11 decimals, and `setSize` calls it. A define is part of the program
 * cache key, so EVERY new stage height is a new SSAO program — compiled and linked inside the
 * first frame composed at that size. MEASURED (unminified release build, headed, Intel D3D11,
 * 2026-09-22, CDP sampling profile of the first viewport resize 1920x1080 -> 1280x900): 134 ms of
 * `getProgramInfoLog` under `SSAOEffect.update -> WebGLProgram.getUniforms -> onFirstUse`, i.e.
 * the link wait, in a 555 ms long animation frame; later resizes back to a height already seen
 * reused the cached program and cost none of it. Opening the Inspector changes the stage size the
 * same way. That first-use link was the Fabric3D FrameRequestCallback E5's sweep put over 200 ms
 * with nothing on screen, for both "open the Inspector" and "resize 1920 -> 1280".
 *
 * The shader uses RADIUS / RADIUS_SQ only in run-time expressions (never in a constant
 * initialiser or a loop bound), so aliasing them to uniforms is exact: same values, one program
 * for every size. The fragment source changes once, at construction, before the warm-up compiles
 * it — so the warm-up links the only SSAO program the session will ever use.
 */
function bindSsaoRadiusAsUniform(material: ShaderMaterial): void {
  const m = material as ShaderMaterial & { r?: number; resolution?: { height: number }; updateRadius?: () => void };
  if (typeof m.updateRadius !== "function" || typeof m.r !== "number" || m.resolution === undefined) return;
  if (!m.fragmentShader.includes("RADIUS")) return;
  const radius = { value: 1 };
  const radiusSq = { value: 1 };
  m.uniforms.atlasSsaoRadius = radius;
  m.uniforms.atlasSsaoRadiusSq = radiusSq;
  delete m.defines.RADIUS;
  delete m.defines.RADIUS_SQ;
  m.fragmentShader =
    "uniform float atlasSsaoRadius;\nuniform float atlasSsaoRadiusSq;\n" +
    "#define RADIUS atlasSsaoRadius\n#define RADIUS_SQ atlasSsaoRadiusSq\n" +
    m.fragmentShader;
  const host = m as { r: number; resolution: { height: number } };
  m.updateRadius = () => {
    const r = host.r * host.resolution.height;
    radius.value = r;
    radiusSq.value = r * r;
  };
  m.updateRadius();
  m.needsUpdate = true;
}

/**
 * The SSAO sampling-rotation noise, generated from a FIXED seed.
 *
 * postprocessing builds this texture with `Math.random()`, so every SSAOEffect gets a different
 * one. That was invisible while SSAO contributed nothing; with occlusion actually reaching the
 * image it means two scenes built from the same data render different pixels, and a capture is no
 * longer reproducible — which is the property the whole capture harness is built on (it waits for
 * `converged` precisely so a screenshot is a fact rather than a sample).
 *
 * MEASURED: with the library's texture, a high -> low -> high round trip produced two different
 * frame hashes; with this one it produces the same hash twice.
 *
 * mulberry32, seeded once. Any deterministic generator would do; what matters is that it is not
 * `Math.random()` and that it does not vary with construction order.
 */
function deterministicSsaoNoise(): DataTexture {
  const size = 64;
  const data = new Uint8Array(size * size * 4);
  let state = 0x9e3779b9;
  for (let i = 0; i < data.length; i += 1) {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    data[i] = ((t ^ (t >>> 14)) >>> 0) % 256;
  }
  const tex = new DataTexture(data, size, size, RGBAFormat, UnsignedByteType);
  // Matches the library's own configuration: the shader tiles this across the frame.
  tex.wrapS = RepeatWrapping;
  tex.wrapT = RepeatWrapping;
  tex.needsUpdate = true;
  return tex;
}

/**
 * Output dither — half a least-significant bit, added last, to break 8-bit quantisation banding.
 *
 * MEASURED before this existed: a vertical luminance scan of the dark stage gradient at x=60 found
 * 8 distinct luma values over 1000 rows, in 22 flat plateaus, the longest 239 px tall. The composer
 * is HalfFloat throughout, so the gradient itself is smooth; the steps appear when the final image
 * is written to an 8-bit framebuffer with nothing to decorrelate the rounding.
 *
 * This is DITHER, not grain, and the difference is exactly what design-brief.md §4.9 item 16
 * forbids: grain is an added texture, animated, of arbitrary amplitude, meant to look filmic. This
 * is a deterministic function of gl_FragCoord — no time, no texture, identical every frame, so a
 * byte-identical capture stays byte-identical — with an amplitude of ±0.5/255, which is smaller
 * than the rounding error it replaces. It cannot make an image noisier than the quantisation it
 * removes; it can only move the rounding decision off a contour line.
 *
 * Interleaved gradient noise rather than a Bayer matrix: one fract() and one dot(), no texture and
 * no array lookup, and its spectrum is closer to blue noise than a 4x4 ordered matrix, which would
 * leave a visible 4-pixel grid on a gradient this shallow.
 *
 * ── WHERE THE NOISE IS ADDED, AND WHY IT IS NOT WHERE IT USED TO BE ─────────────────────────────
 *
 * "±0.5/255" is a statement about the DISPLAY-REFERRED image — the 8-bit values the quantiser
 * rounds. An `Effect` does not run there. `EffectPass` merges every effect into one shader whose
 * assembled main() is (node_modules/postprocessing/build/index.js, EffectMaterial's fragment
 * source):
 *
 *     FRAGMENT_MAIN_IMAGE            <- every effect, including this one
 *     gl_FragColor = color0;
 *     #ifdef ENCODE_OUTPUT
 *     #include <colorspace_fragment>  <- the linear -> sRGB encode
 *     #endif
 *
 * So a constant added in mainImage is added to LINEAR radiance and then stretched by the sRGB
 * OETF, whose slope near black is ~12.92. MEASURED on the dark stage, with the amplitude below
 * written as a linear offset: a 5x5 peak-to-peak scan of pure backdrop (no geometry in the band)
 * averaged 11.7 levels at mean luminance 10, and 15.64 % of the backdrop's red channel CLIPPED to
 * zero — a structured, plainly visible checker over the whole stage, about twelve times the
 * amplitude the comment claimed, on the one surface the comment was written for. On bright light
 * surfaces the same code measured ~1 level, because there the OETF slope is ~1. That ratio is the
 * signature: the amplitude was scaling as the inverse of the transfer slope.
 *
 * The fix is to dither where the quantiser is. The effect encodes to display space, adds half an
 * LSB THERE, and decodes back to linear so the pass's own encode reproduces exactly the display
 * value intended. One pow() round trip in a fullscreen pass that already existed; no new pass, no
 * new pass ordering, and the capture stays byte-identical because the noise is still a pure
 * function of gl_FragCoord.
 *
 * `max(…, 0.0)` on the dithered display value, not a clamp to 1: a negative display value would
 * come back through the decode as a NaN-producing pow() of a negative base, and the quantiser
 * already clips at 0 — but it now clips only where the true display value is under half an LSB,
 * i.e. where the image really is black, instead of wherever the noise happened to land.
 *
 * `encodesOutput` is false when this pass's result is NOT sRGB-encoded downstream (nothing in this
 * application currently does that — the renderer's output colour space is sRGB and this is always
 * the final pass — but a future linear output target would make the round trip a lie, so the
 * decision is made from the renderer rather than assumed).
 */
class DitherEffect extends Effect {
  constructor(encodesOutput: boolean) {
    super(
      "DitherEffect",
      encodesOutput
        ? `vec3 atlasEncode(const in vec3 c) {
          vec3 v = max(c, vec3(0.0));
          return mix(v * 12.92, 1.055 * pow(v, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), v));
        }
        vec3 atlasDecode(const in vec3 c) {
          vec3 v = max(c, vec3(0.0));
          return mix(v / 12.92, pow((v + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), v));
        }
        void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
          float n = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
          vec3 display = atlasEncode(inputColor.rgb) + (n - 0.5) / 255.0;
          outputColor = vec4(atlasDecode(display), inputColor.a);
        }`
        : `void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
          float n = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
          outputColor = vec4(inputColor.rgb + (n - 0.5) / 255.0, inputColor.a);
        }`,
      { blendFunction: BlendFunction.NORMAL },
    );
  }
}

export function createPostChain(opts: PostChainOptions): PostChain {
  const { renderer, scene, camera, profile } = opts;

  /* The camera's depth RANGE is the unit every normalised SSAO threshold below is expressed in.
     Read off the live camera rather than hard-coded: the rig fits near/far to the fabric's bounding
     sphere, so a different snapshot moves them. Guarded because `Camera` carries no near/far. */
  const view = camera as Partial<{ near: number; far: number }>;
  const depthSpan = Math.max(1, (view.far ?? 1000) - (view.near ?? 0.1));

  const composer = new EffectComposer(renderer, {
    // UnsignedByte bands visibly on a near-black stage and clips emissive at 1.0, which would
    // leave a luminanceThreshold of 1.0 with nothing above it to find.
    frameBufferType: HalfFloatType,
    /* Zero, and MEASURED zero rather than assumed. 4x MSAA on this composer was the obvious
       candidate for the cable aliasing and it made the picture WORSE, twice, reproducibly:
       zero-intermediate background-to-cable crossings at `high` went 63.5 % -> 72.8 % on the
       repo's own metric and 42.5 % -> 59.6 % on a threshold-free one, and the strokes came out
       chunkier at 8x. Per-sample coverage quantises a 1.5-3 px stroke's edge to five levels and
       then leaves SMAA with a locally-clean image it declines to filter further. The cables are
       anti-aliased analytically instead, in geometry/cables.ts, where the exact edge is known.
       Numbers in docs/render-decisions.md. */
    multisampling: 0,
  });

  const passEffects = new Map<Pass, string[]>();

  const renderPass = new RenderPass(scene, camera);
  composer.addPass(renderPass);

  const normalPass = new NormalPass(scene, camera);
  const depthDown = new DepthDownsamplingPass({
    normalBuffer: normalPass.texture,
    resolutionScale: profile.ssaoResolutionScale,
  });

  let ssao: SSAOEffect | null = null;
  let ssaoPass: EffectPass | null = null;
  let ssaoNoise: DataTexture | null = null;
  if (profile.ssao) {
    composer.addPass(normalPass);
    composer.addPass(depthDown);
    ssao = new SSAOEffect(camera, normalPass.texture, {
      blendFunction: BlendFunction.MULTIPLY,
      distanceScaling: true,
      depthAwareUpsampling: true,
      normalDepthBuffer: depthDown.texture,
      samples: profile.ssaoSamples,
      rings: profile.ssaoRings,
      luminanceInfluence: 0.6,
      radius: 0.09,
      intensity: 1.55,
      bias: 0.03,
      fade: 0.015,
      resolutionScale: profile.ssaoResolutionScale,
      /* Occlusion cutoffs, in NORMALISED depth, computed here rather than handed to the library's
       * `world*` setters.
       *
       * The previous values (worldDistanceThreshold 260, worldDistanceFalloff 48,
       * worldProximityThreshold 14, worldProximityFalloff 5) were written as SCENE-SPAN numbers —
       * "the fabric spans ~330 and tiers sit 64 apart". That is not what they mean. Each `world*`
       * setter runs its argument through `viewZToOrthographicDepth(-value, camera.near,
       * camera.far)`, i.e. it is a DISTANCE FROM THE CAMERA mapped onto the near..far range, and
       * this scene's camera sits at near 135 / far 608.5 with the fabric ~353 units away:
       *
       *   distance cutoff  ->  (0.264, 0.365) normalised, while the fabric's own depth is ~0.46
       *                        the shader's `if (linearDepth < distanceCutoff.y)` was false for
       *                        every pixel of the fabric
       *   proximity cutoff ->  14 and 5 map to NEGATIVE depths, clamped to 0, so the per-sample
       *                        test `if (proximity < proximityCutoff.y)` became `< 0.0` and no
       *                        sample could ever contribute
       *
       * Two independent zeroes, which is why SSAO rendered every frame and changed no pixel: a
       * pass that is present, enabled, measured at 0.00% of the frame, and grounding nothing while
       * geometry/ground.ts says "its grounding comes from SSAO and the contact decals instead".
       *
       * The distance cutoff is the library's own default (0.97/0.03) — effectively "do not fade
       * occlusion out by distance", which is right for a bounded fabric that is entirely inside
       * the frustum. The proximity window is a real world-unit intention converted against the
       * depth range it is actually measured in: samples within ~3 units of the shaded point
       * occlude it, fading out by ~9. Chassis are 4-8 units tall and sit 2 units above their deck,
       * so that window is "this surface and the thing it stands on", not a neighbouring tier. */
      distanceThreshold: 0.97,
      distanceFalloff: 0.03,
      rangeThreshold: AO_PROXIMITY_WORLD / depthSpan,
      rangeFalloff: AO_PROXIMITY_FALLOFF_WORLD / depthSpan,
    });
    ssaoNoise = deterministicSsaoNoise();
    // The library generated one from Math.random() in the constructor; replace it and free it.
    const generated = ssao.ssaoMaterial.noiseTexture;
    ssao.ssaoMaterial.noiseTexture = ssaoNoise;
    if (generated !== null && generated !== undefined) generated.dispose();
    bindSsaoRadiusAsUniform(ssao.ssaoMaterial);
    ssaoPass = new EffectPass(camera, ssao);
    passEffects.set(ssaoPass, ["SSAOEffect"]);
    composer.addPass(ssaoPass);
  }

  const bloom = new SelectiveBloomEffect(scene, camera, {
    blendFunction: BlendFunction.SCREEN,
    // kernelSize / resolutionScale on BloomEffect are deprecated in favour of the mipmap chain.
    mipmapBlur: true,
    levels: profile.bloomLevels,
    /* Tent radius of the upsample, and the other half of the "the pass delivered nothing" fix
       recorded on `QualityProfile.bloomLevels`.
       MEASURED at levels 8 / radius 0.82 / intensity 0.62: the annulus means at 0-3, 3-6, 6-10,
       10-16, 16-24 and 24-40 px around a focused device's status LED were
       [51.25, 36.73, 34.47, 29.61, 32.55, 54.56] with bloom ON at `high`, against
       [51.37, 36.63, 34.44, 29.47, 32.68, 54.74] at `low`, where the profile DISABLES bloom
       outright — eighteen numbers agreeing to within 0.2/255. A wide tent over a tall pyramid
       spreads a 2-4 px emitter's energy below the noise floor of the image it is added to.
       Narrow and stronger: the light lands on the emitter and within a few pixels of it, which is
       what "this element is emitting" has to look like to be readable at all. */
    radius: 0.3,
    intensity: 1.15,
    // Never lowered to make something glow. If an element should glow, raise its
    // emissiveIntensity — that keeps "glowing" meaning "emitting" instead of meaning "bright".
    luminanceThreshold: 1,
    luminanceSmoothing: 0.03,
  });
  bloom.inverted = false;
  bloom.ignoreBackground = true;

  const selectionOutline = new OutlineEffect(scene, camera, {
    blendFunction: BlendFunction.SCREEN,
    edgeStrength: 3.4,
    pulseSpeed: 0, // nothing in this product pulses without a reason, and selection has none
    visibleEdgeColor: opts.tokens.color("--accent").getHex(),
    hiddenEdgeColor: opts.tokens.color("--accent").getHex(),
    kernelSize: KernelSize.VERY_SMALL,
    blur: false,
    // The occluded part of a selected chassis still shows its edge. Losing the selection because
    // it slid behind another tier would be the "context destroyed" failure in miniature.
    xRay: true,
    resolutionScale: profile.outlineResolutionScale,
  });

  const blockedOutline = new OutlineEffect(scene, camera, {
    blendFunction: BlendFunction.SCREEN,
    edgeStrength: 5.2,
    pulseSpeed: 0,
    visibleEdgeColor: opts.tokens.color("--sev-critical").getHex(),
    hiddenEdgeColor: opts.tokens.color("--sev-critical").getHex(),
    kernelSize: KernelSize.SMALL,
    blur: true,
    xRay: true,
    resolutionScale: profile.outlineResolutionScale,
  });

  /* Pin the render layers these three effects select on.
   *
   * Every postprocessing `Selection` takes the next id from a module-global counter that never
   * resets (see layers.ts for the measurement). Left alone, the SECOND chain built in a page lands
   * on 5/6/7 and 7 is PICK_LAYER — at which point OutlineEffect's first frame, which runs with an
   * empty selection because its constructor sets `forceUpdate = true`, renders the hit-test
   * proxies into its mask and leaves that mask composited forever. That is the all-chassis red
   * glow. Assigning here is the whole fix: `Selection.layer`'s setter moves any current members,
   * and these sets are empty at construction, so it is a plain reassignment. */
  bloom.selection.layer = SELECTION_LAYERS.bloom;
  selectionOutline.selection.layer = SELECTION_LAYERS.selectionOutline;
  blockedOutline.selection.layer = SELECTION_LAYERS.blockedOutline;

  /* Read them BACK. Pinning is an instruction; this is the evidence. If a future version of the
   * library ignores the assignment the failure is a message, not a red fabric. */
  const layerViolations = assertLayerRegistry([
    ["bloom", bloom.selection.layer],
    ["selectionOutline", selectionOutline.selection.layer],
    ["blockedOutline", blockedOutline.selection.layer],
  ]);
  if (layerViolations.length > 0 && import.meta.env?.DEV === true) {
    // eslint-disable-next-line no-console
    console.error("fabric3d: render-layer collision", layerViolations);
  }

  const glowEffects = [
    ...(profile.bloom ? [bloom] : []),
    ...(profile.outline ? [selectionOutline, blockedOutline] : []),
  ];
  let glowPass: EffectPass | null = null;
  if (glowEffects.length > 0) {
    glowPass = new EffectPass(camera, ...glowEffects);
    passEffects.set(glowPass, glowEffects.map((e) => e.constructor.name));
    composer.addPass(glowPass);
  }

  const tone = new ToneMappingEffect({
    mode: opts.toneMapping === "neutral" ? ToneMappingMode.NEUTRAL : ToneMappingMode.AGX,
  });
  const smaa = new SMAAEffect({
    preset: profile.smaaPreset,
    // COLOR detection, not DEPTH: many edges here are colour boundaries on coplanar surfaces —
    // severity bands, bezel glyphs, port grids — which carry no depth discontinuity at all.
    edgeDetectionMode: EdgeDetectionMode.COLOR,
  });
  /* Read off the renderer, not assumed: the round trip above is only correct when the encode it
     undoes actually happens downstream. `SRGBColorSpace` is three's string constant "srgb". */
  const dither = new DitherEffect(renderer.outputColorSpace === SRGBColorSpace);
  /* The previous presented frame (see HISTORY_AA). Sized to the drawing buffer on first capture. */
  let historyTexture = createHistoryTexture(1, 1);
  const history = new HistoryEffect(historyTexture, renderer.outputColorSpace === SRGBColorSpace);
  let historyValid = false;
  let historyRequested = 0;
  let historyUsed = 0;
  const drawingBuffer = new Vector2();

  /* Tone mapping gets its OWN EffectPass, and that is the whole fix for the cable aliasing.
   *
   * `EffectPass` merges its effects into ONE fragment shader, so effects listed in it run in
   * order on a value. `SMAAEffect` is not that kind of effect. It carries
   * `EffectAttribute.CONVOLUTION` and does its real work in `update(renderer, inputBuffer)`, which
   * runs its edge-detection and weights passes over `inputBuffer` — the buffer handed to the WHOLE
   * EffectPass — before the merged shader executes at all
   * (node_modules/postprocessing/build/index.js, SMAAEffect#update). So inside
   * `EffectPass(tone, smaa, dither)` the edge detector never saw the tone-mapped image: it saw the
   * raw HalfFloat HDR buffer, whichever side of `tone` the effect was listed on.
   *
   * That is why the A/B the brief demanded came back BYTE-IDENTICAL in both orders — the flag could
   * not move anything — and it is why aliasing was WORSE at `high` than at the upsampling tiers.
   * SMAA is a perceptual filter: its threshold, and especially its local-contrast adaptation step
   * (an edge is discarded when its delta is small next to the largest neighbouring delta), are
   * specified against display-referred values in [0,1]. On this scene it was being fed unbounded
   * linear radiance over a near-black stage, where a thin bright stroke's edge is numerically tiny
   * beside the specular highlights elsewhere in the kernel, and was being thrown away.
   *
   * One extra fullscreen pass, one extra draw call. The order is now SETTLED rather than inferred,
   * and the numbers are in docs/render-decisions.md. */
  const addPass = (...effects: Effect[]): void => {
    const pass = new EffectPass(camera, ...effects);
    passEffects.set(pass, effects.map((e) => e.constructor.name));
    composer.addPass(pass);
  };
  /* The history blend sits after SMAA (it stabilises SMAA's own per-frame decisions) and before the
     dither (so the output is still dithered exactly once, at the quantiser). */
  if (profile.smaa) {
    addPass(tone);
    addPass(smaa, history, dither);
  } else {
    // Nothing for the split to buy on a tier with no SMAA: keep it to one pass.
    addPass(tone, history, dither);
  }

  const bloomSelection = new Set<Object3D>();

  /* Last projection handed to the bloom's depth mask; see `syncCamera`. NaN so the first call
     always lands, whatever the camera is holding at construction. */
  let lastCameraNear = Number.NaN;
  let lastCameraFar = Number.NaN;

  const chain: PostChain = {
    composer,
    bloomSelection,

    setBloomObjects(objects: readonly Object3D[]): void {
      bloomSelection.clear();
      for (const o of objects) bloomSelection.add(o);
      bloom.selection.set(objects as Object3D[]);
    },

    setSelectionOutline(objects: readonly Object3D[]): void {
      selectionOutline.selection.set(objects as Object3D[]);
    },

    setBlockedOutline(objects: readonly Object3D[]): void {
      blockedOutline.selection.set(objects as Object3D[]);
    },

    outlinesUpdatingNextRender(): number {
      if (!profile.outline) return 0;
      let n = 0;
      for (const effect of [selectionOutline, blockedOutline]) {
        // `forceUpdate` is a public field in postprocessing 6.x but absent from its typings.
        const pending = (effect as unknown as { forceUpdate?: boolean }).forceUpdate === true;
        if (pending || effect.selection.size > 0) n += 1;
      }
      return n;
    },

    setMotion(inMotion: boolean): boolean {
      if (ssaoPass === null) return false;
      const on = !inMotion;
      if (ssaoPass.enabled !== on) {
        normalPass.enabled = on;
        depthDown.enabled = on;
        ssaoPass.enabled = on;
        /* The picture changes for a reason other than the camera: the last frame is no history. */
        historyValid = false;
      }
      return true;
    },

    setSize(width: number, height: number): void {
      // composer.setSize, never renderer.setSize: the composer owns every render target in the
      // chain, and resizing the renderer alone leaves the passes at the old size with no error.
      //
      // updateStyle MUST be false. It defaults to true, which writes an inline width/height in CSS
      // pixels onto the canvas element — so the canvas stops being sized by the stylesheet and
      // starts being sized by whatever we last measured. The failure is self-reinforcing and
      // silent: measure 1px at construction, write style="width:1px", measure 1px forever.
      composer.setSize(width, height, false);
      historyValid = false;
    },

    /**
     * Keep the SELECTIVE bloom's depth mask on the camera the scene is actually using.
     *
     * THIS IS WHY THE BLOOM PASS DELIVERED NOTHING. `SelectiveBloomEffect` does not read the
     * camera's projection per frame: its constructor calls `depthMaskMaterial.copyCameraSettings(
     * camera)` once, and the mask shader then linearises BOTH depth buffers — the scene's own
     * depth attachment and the layer-masked depth it renders itself — through those cached
     * near/far values before testing them for equality. This camera rig re-fits near/far to the
     * fabric's bounding sphere after the chain is built, so the cached pair went stale on the
     * first reframe.
     *
     * MEASURED, live, by patching the library's `update` on the running page: cached
     * `cameraNearFar` [135, 608.5] against a live camera of [26, 499]; the masked render target
     * read back empty, the luminance and bloom targets with it, and the annulus means around a
     * focused device's LED agreed with the bloom-DISABLED tier to within 0.2/255 at every radius
     * from 0 to 40 px. Re-copying the camera settings each frame and changing nothing else moved
     * pixels immediately (38 px at max |Δ| 385 on a wide-open threshold), so the mask had been
     * discarding the whole frame rather than selecting nothing from it.
     *
     * Guarded on the values rather than called unconditionally: the setter also reassigns the
     * internal depth pass's camera, and this runs on every rendered frame.
     */
    syncCamera(): void {
      const cam = camera as Partial<{ near: number; far: number }>;
      const near = cam.near ?? 0;
      const far = cam.far ?? 0;
      if (near === lastCameraNear && far === lastCameraFar) return;
      lastCameraNear = near;
      lastCameraFar = far;
      bloom.mainCamera = camera;
    },

    retint(tokens: TokenPalette): void {
      historyValid = false;
      selectionOutline.visibleEdgeColor.set(tokens.color("--accent").getHex());
      selectionOutline.hiddenEdgeColor.set(tokens.color("--accent").getHex());
      blockedOutline.visibleEdgeColor.set(tokens.color("--sev-critical").getHex());
      blockedOutline.hiddenEdgeColor.set(tokens.color("--sev-critical").getHex());
    },

    describe(): string[] {
      // Read from a record kept at construction rather than from EffectPass's private `effects`
      // field: the invariant test must fail when WE reorder the chain, not when the library
      // renames an internal.
      return composer.passes.map((pass) => {
        const inner = passEffects.get(pass);
        return inner === undefined || inner.length === 0
          ? pass.constructor.name
          : `${pass.constructor.name}(${inner.join(",")})`;
      });
    },

    setHistoryWeight(weight: number): void {
      historyRequested = Number.isFinite(weight) ? Math.min(HISTORY_AA.weight, Math.max(0, weight)) : 0;
    },

    historyWeightUsed(): number {
      return historyUsed;
    },

    captureHistory(): void {
      renderer.getDrawingBufferSize(drawingBuffer);
      const w = Math.max(1, Math.floor(drawingBuffer.x));
      const h = Math.max(1, Math.floor(drawingBuffer.y));
      if (historyTexture.image.width !== w || historyTexture.image.height !== h) {
        historyTexture.dispose();
        historyTexture = createHistoryTexture(w, h);
        history.history.value = historyTexture;
      }
      /* The canvas, straight after the presenting render and before the browser composites it:
         the default framebuffer (antialias off, so single-sampled) still holds the frame. */
      renderer.setRenderTarget(null);
      renderer.copyFramebufferToTexture(historyTexture);
      historyValid = true;
    },

    render(deltaSeconds: number): void {
      historyUsed = historyValid ? historyRequested : 0;
      historyRequested = 0;
      history.weight.value = historyUsed;
      composer.render(deltaSeconds);
    },

    dispose(): void {
      // composer.dispose() disposes every pass it holds, plus Pass.fullscreenGeometry — which is
      // static and shared. Disposing a BufferGeometry only releases its GPU buffers, so a later
      // composer re-uploads it; this is safe, but it is the reason a second scene on the same page
      // must not be created between dispose and re-create expecting warm buffers.
      composer.dispose();
      // Anything the composer never held is not reached by that call, so it is released here and
      // ONLY here — double-disposing an effect is how a "leak fix" turns into a use-after-free.
      if (ssaoPass === null) {
        normalPass.dispose();
        depthDown.dispose();
        if (ssao !== null) ssao.dispose();
      }
      if (glowPass === null) {
        bloom.dispose();
        selectionOutline.dispose();
        blockedOutline.dispose();
      }
      if (ssaoNoise !== null) ssaoNoise.dispose();
      historyTexture.dispose();
      bloomSelection.clear();
    },
  };

  return chain;
}
