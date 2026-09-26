/**
 * quality.ts — probe the GPU once, choose a tier, and say out loud why.
 *
 * The rule this file exists to enforce: degradation is never silent. A scene that quietly drops
 * shadows on a weak GPU produces a screenshot a critic reads as "they forgot shadows", and a user
 * being shown a cheaper render has no way to know it is cheaper. So every decision carries a
 * human-readable reason, the reasons ride along on `stats()`, and the reason list is non-empty even
 * when the answer is "high" — absence of a complaint is not evidence of a capable GPU, it is
 * evidence that nobody asked.
 */
import { SMAAPreset } from "postprocessing";
import type { WebGLRenderer } from "three";
import type { QualityTier } from "./contract";

export interface GpuCapabilities {
  webgl2: boolean;
  maxTextureSize: number;
  maxSamples: number;
  maxAnisotropy: number;
  /** UNMASKED_RENDERER_WEBGL when the extension is exposed; null when the browser masks it. */
  rendererName: string | null;
  /** A software rasteriser (SwiftShader / llvmpipe / ANGLE software) — the one hard "go low" signal. */
  software: boolean;
  floatLinearFiltering: boolean;
  hardwareConcurrency: number | null;
  deviceMemoryGb: number | null;
}

export interface QualityProfile {
  tier: QualityTier;
  /** Hard cap on devicePixelRatio. A separate knob from renderScale — never conflate the two. */
  maxPixelRatio: number;
  /** Internal render scale applied on top of the (capped) DPR. */
  renderScale: number;
  shadows: boolean;
  shadowMapSize: number;
  ssao: boolean;
  ssaoSamples: number;
  ssaoRings: number;
  ssaoResolutionScale: number;
  bloom: boolean;
  /**
   * Mip levels in the bloom's blur pyramid — i.e. HOW FAR a bloomed pixel's light is spread.
   *
   * Not a quality dial in the usual sense, and it was being treated as one. Level n blurs at
   * 1/2^n of the frame, so 8 levels smear a status LED's energy across a 6x3 mip of a 1600x900
   * frame; MEASURED at 8 levels / radius 0.82, the mean luminance in every annulus from 0 to 40 px
   * around a focused device's LED agreed with the bloom-DISABLED tier to within 0.2/255. The pass
   * ran, cost its draw calls, and deposited nothing — while the product documents a glow as
   * meaning "this element is emitting".
   *
   * The emitters in this scene are 2-4 px. Their light has to land ON them and within a few pixels
   * of them, so the pyramid is short and the tent narrow (see `radius` in postfx.ts). Fewer levels
   * is also strictly cheaper.
   */
  bloomLevels: number;
  smaa: boolean;
  smaaPreset: SMAAPreset;
  outline: boolean;
  outlineResolutionScale: number;
  /** Environment cubemap edge length handed to PMREMGenerator. */
  envSize: number;
  anisotropy: number;
  /** Samples per cable polyline. Too few and the curves read faceted, so this floor is high. */
  cableSegments: number;
  /** Rounded-box corner segments on the chassis. 1 still bevels; 0 would be a hard-edged box. */
  chassisBevelSegments: number;
  /** Lid louvers, screws and ear dimples. Tier-INDEPENDENT — see SCENE_DETAIL. */
  chassisFineDetail: boolean;
}

export interface QualityDecision {
  tier: QualityTier;
  /** Why this tier, in words a status bar can print. Never empty. */
  reasons: string[];
  /** True when the tier was chosen by the probe rather than handed in by the caller. */
  auto: boolean;
}

const UNKNOWN_RENDERER = "renderer identity masked by the browser (WEBGL_debug_renderer_info absent)";

/** Substrings identifying a CPU rasteriser. Matched case-insensitively against the renderer string. */
const SOFTWARE_MARKERS = ["swiftshader", "llvmpipe", "software", "basic render", "microsoft basic"];

export function probeCapabilities(renderer: WebGLRenderer): GpuCapabilities {
  const gl = renderer.getContext();
  const caps = renderer.capabilities;

  let rendererName: string | null = null;
  // The extension is deliberately absent in privacy-hardened browsers. That is a legitimate
  // answer, not an error, and it must not be read as "therefore not a software renderer".
  const dbg = gl.getExtension("WEBGL_debug_renderer_info");
  if (dbg !== null) {
    const raw: unknown = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
    if (typeof raw === "string" && raw.length > 0) rendererName = raw;
  }

  const lower = rendererName === null ? "" : rendererName.toLowerCase();
  const software = SOFTWARE_MARKERS.some((m) => lower.includes(m));

  const nav: Partial<Navigator> & { deviceMemory?: number } =
    typeof navigator === "undefined" ? {} : navigator;

  return {
    webgl2: typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext,
    maxTextureSize: caps.maxTextureSize,
    maxSamples: caps.maxSamples,
    maxAnisotropy: caps.getMaxAnisotropy(),
    rendererName,
    software,
    floatLinearFiltering: gl.getExtension("OES_texture_float_linear") !== null,
    hardwareConcurrency:
      typeof nav.hardwareConcurrency === "number" ? nav.hardwareConcurrency : null,
    deviceMemoryGb: typeof nav.deviceMemory === "number" ? nav.deviceMemory : null,
  };
}

/**
 * Tier selection. Ordered most-severe-signal first so the first matching rule wins and the reason
 * printed is the reason that actually decided it, not the last one evaluated.
 */
export function chooseQuality(caps: GpuCapabilities): QualityDecision {
  const reasons: string[] = [];

  if (caps.software) {
    /* The consequence is DERIVED from the profile, not written by hand. It used to say "shadows
       and SSAO disabled" — but the shadow map is off at every tier (SHADOW_MAP_REASON), and the
       dominant visible change at low is the bloom (C5 audit, 2026-09-22: the high-vs-low diff is
       the LED halos). A hand-written list of what a tier drops rots the moment a profile moves. */
    reasons.push(
      `software rasteriser detected (${caps.rendererName ?? "unnamed"}) — ${tierConsequence("low")}`,
    );
    return { tier: "low", reasons, auto: true };
  }
  if (!caps.webgl2) {
    reasons.push("WebGL 2 unavailable — depth-aware and multisampled passes cannot run");
    return { tier: "low", reasons, auto: true };
  }
  if (caps.maxTextureSize < 4096) {
    reasons.push(
      `max texture size ${caps.maxTextureSize} < 4096 — environment and shadow maps reduced`,
    );
    return { tier: "low", reasons, auto: true };
  }
  if (caps.deviceMemoryGb !== null && caps.deviceMemoryGb <= 2) {
    reasons.push(`navigator.deviceMemory reports ${caps.deviceMemoryGb} GB — render targets reduced`);
    return { tier: "low", reasons, auto: true };
  }

  if (caps.hardwareConcurrency !== null && caps.hardwareConcurrency <= 4) {
    reasons.push(
      `${caps.hardwareConcurrency} logical cores — shader compilation and upload budget reduced`,
    );
    return { tier: "balanced", reasons, auto: true };
  }
  if (caps.maxAnisotropy < 8) {
    reasons.push(`max anisotropy ${caps.maxAnisotropy} < 8 — grazing-angle texture quality limited`);
    return { tier: "balanced", reasons, auto: true };
  }
  if (caps.maxSamples < 4) {
    reasons.push(`max MSAA samples ${caps.maxSamples} < 4 — outline pass multisampling unavailable`);
    return { tier: "balanced", reasons, auto: true };
  }

  reasons.push(
    `${FULL_QUALITY_PREFIX}WebGL 2, ${caps.maxTextureSize}px textures, ${caps.maxAnisotropy}x anisotropy, ` +
      (caps.rendererName ?? UNKNOWN_RENDERER),
  );
  return { tier: "high", reasons, auto: true };
}

/** The probe's sentence for a capable GPU starts with this, and ONLY that sentence does. */
export const FULL_QUALITY_PREFIX = "full quality: ";

/** Profile switches a tier can turn off, in the words a status line uses. */
const TIER_FEATURES: readonly [keyof QualityProfile, string][] = [
  ["ssao", "SSAO"],
  ["bloom", "bloom"],
  ["outline", "outline passes"],
  ["shadows", "shadow map"],
];

/**
 * What `tier` turns off relative to `high`, read off the two profiles — e.g. "SSAO, bloom and
 * outline passes disabled". A switch that is off at `high` too (the shadow map) is not a
 * consequence of the tier and is not listed; SHADOW_MAP_REASON states it at every tier.
 */
export function tierConsequence(tier: QualityTier): string {
  const hi = PROFILES.high;
  const p = PROFILES[tier];
  const off = TIER_FEATURES.filter(([k]) => hi[k] === true && p[k] === false).map(([, name]) => name);
  if (off.length === 0) return "every effect kept; cheaper sampling and environment only";
  const list = off.length === 1 ? off[0] : `${off.slice(0, -1).join(", ")} and ${off[off.length - 1]}`;
  return `${list} disabled`;
}

/**
 * The capability probe's reasons, restated for the tier actually in force.
 *
 * The probe speaks about the tier IT chose. After an automatic step-down its sentence still read
 * "full quality: WebGL 2, ..." next to "stepped down to low: ..." (E4 audit, 2026-09-22) — a
 * status line claiming full quality while rendering the cheapest tier. The probe's evidence is
 * kept (it is still true of the GPU), but a sentence that names a tier no longer in force is
 * reworded to say which tier it chose and which one is running.
 */
export function probeReasonsAt(probe: QualityDecision, tier: QualityTier): string[] {
  if (probe.tier === tier) return [...probe.reasons];
  return probe.reasons.map((r) => {
    const body = r.startsWith(FULL_QUALITY_PREFIX) ? r.slice(FULL_QUALITY_PREFIX.length) : r;
    return `capability probe chose ${probe.tier} (${body}); running at ${tier} — ${tierConsequence(tier)}`;
  });
}

/**
 * Whether the adaptive step-down may still move this tier: it was chosen by the session for itself
 * (`auto`) and is not already the floor. The scene's step-down judge and its held step-down both
 * gate on this one predicate, so a caller-pinned tier is outside the step-down at both sites at
 * once. (The hidden-page step-up gates on `auto` alone, since `low` may step back up.)
 */
export function tierIsAdaptive(d: QualityDecision): boolean {
  return d.auto && d.tier !== "low";
}

/** What a caller's `setQuality(q)` does to the decision in force. */
export interface QualityPin {
  /** The decision in force afterwards. Always `auto: false` — a caller's tier is a pin. */
  decision: QualityDecision;
  /** True when the tier CHANGES, so the post chain (and perhaps the graph) must be rebuilt. */
  rebuild: boolean;
}

/**
 * A caller's tier is a PIN, including the tier already in force.
 *
 * `setQuality(q)` used to return early when `q` was the current tier, so asking for the tier the
 * probe had auto-selected left the decision `auto` — and the adaptive step-down then moved it. The
 * C5 motion harness pinned its HIGH legs that way and, on a contended Intel iGPU (2026-09-23), both
 * were stepped down to balanced mid-orbit and four C5 items graded on the wrong tier. Asking for the
 * tier you already have is asking to keep it. The same-tier pin changes nothing drawn, so it needs
 * no rebuild and no warm-up (the tier-change path, which re-warms the chain, is not entered) — it is
 * safe to call mid-motion. Re-pinning the tier already pinned is a no-op: the decision in force is
 * returned as it is (same object), with its caller's reason intact.
 */
export function pinQuality(current: QualityDecision, q: QualityTier): QualityPin {
  if (q === current.tier && !current.auto) return { decision: current, rebuild: false };
  const decision: QualityDecision = { tier: q, reasons: [`quality tier "${q}" set by the caller`], auto: false };
  return { decision, rebuild: q !== current.tier };
}

/**
 * THE SHADOW MAP IS OFF AT EVERY TIER, and that is a decision, not a degradation.
 *
 * Render audit #6 asked for one of two things: make the directional shadow measurable, or stop
 * paying for it and say so. It was not measurable. The key sits 52° above the horizon over rack
 * units 3 tall and 16 wide, so the geometry can only throw a ~1.6-unit crescent at the base
 * (lighting.ts states the arithmetic), and at the normalBias that removes the inter-part acne the
 * crescent is mostly gone too. MEASURED 2026-09-21 on a real GPU (tier high, dark, podacc1 focused
 * and dollied four ticks, 320x220 crop): shadows-on vs shadows-off changed 0.497 % of the crop's
 * pixels at a mean delta of 0.207/255 — against exactly 0 between two shadows-on captures. A 2048²
 * map for a fifth of a level is cost with no picture.
 *
 * Grounding is carried at every tier by what was already carrying it: the contact decal under
 * every chassis, and a surface pad under every chassis the tier deck fades away from
 * (geometry/ground.ts, which asserts per node that there is a surface to ground on). The lighting
 * rig still configures the key's shadow, so turning it back on is this one constant, and
 * `qualityReasons` says what is off and why at every tier, so the choice is never silent.
 */
export const SHADOW_MAP_IN_USE = false;

export const SHADOW_MAP_REASON =
  "shadow map off at every tier: measured at 0.5 % of a focused-chassis crop (mean delta 0.2/255); " +
  "grounding is the contact decal plus a surface pad under every node; SSAO does not ground (the ground planes write no depth, so it has nothing to occlude there) and only shades chassis crevices";

/**
 * THE SCENE'S GEOMETRY AND TEXTURE DETAIL ARE THE SAME AT EVERY TIER (design-brief §4.9 #11:
 * "Geometry has no LOD at 26 nodes").
 *
 * These four fields used to step with the tier — 3/2/1 bevel segments, lid louvers on or off,
 * 28/20/14 cable samples, 8x/4x/4x anisotropy — so a tier change REBUILT the fabric's geometry.
 * MEASURED (C5 critic, reproduced 2026-09-21 on ANGLE → Intel D3D11, core1 focused and dollied):
 * setQuality('low') swapped every lid's vent louvers for a flat dark rectangle in one frame
 * (high-vs-low 2.9 % of the crop changed, 0.46 % by more than 60/255, concentrated on the lids), and
 * the automatic step-down fires that swap mid-gesture on an integrated GPU. A cross-fade over the
 * post chain cannot hide a change of SHAPE.
 *
 * The whole fabric is ~26 chassis and ~60 cables; the fine detail is a few thousand triangles and
 * no extra draw calls (it is merged per material and instanced), so it is never what a slow frame
 * is paying for. The tier now moves only cost that has no shape: render scale, DPR cap, SSAO,
 * bloom, outlines and the SMAA preset. `geometryKey` (scene.ts) is therefore equal for every tier,
 * and a tier change no longer rebuilds the graph at all.
 */
export const SCENE_DETAIL = Object.freeze({
  anisotropy: 8,
  cableSegments: 28,
  chassisBevelSegments: 3,
  chassisFineDetail: true,
});

const PROFILES: Readonly<Record<QualityTier, QualityProfile>> = Object.freeze({
  high: Object.freeze({
    tier: "high",
    maxPixelRatio: 2,
    renderScale: 1,
    shadows: SHADOW_MAP_IN_USE,
    shadowMapSize: 2048,
    ssao: true,
    ssaoSamples: 16,
    ssaoRings: 7,
    ssaoResolutionScale: 0.5,
    bloom: true,
    bloomLevels: 4,
    smaa: true,
    smaaPreset: SMAAPreset.ULTRA,
    outline: true,
    outlineResolutionScale: 0.5,
    envSize: 256,
    ...SCENE_DETAIL,
  }),
  balanced: Object.freeze({
    tier: "balanced",
    /* Was 1.5. See MIN_PIXEL_RATIO: on a DPR 2 display 1.5 rendered at 0.75x and let the compositor
       upsample it (independent audit C5, 2026-09-22). */
    maxPixelRatio: 2,
    /* Was 0.85: 1.5 x 0.85 = 1.275 device pixels per CSS pixel, a sub-native buffer upsampled by
       the compositor on every HiDPI display — the same smear `low` had. See MIN_PIXEL_RATIO. */
    renderScale: 1,
    shadows: SHADOW_MAP_IN_USE,
    shadowMapSize: 1024,
    ssao: true,
    ssaoSamples: 9,
    ssaoRings: 5,
    ssaoResolutionScale: 0.5,
    bloom: true,
    bloomLevels: 3,
    smaa: true,
    /* ULTRA at every tier (design-brief §4.9 item 2). At ~31 draw calls the preset's extra search
       steps are not what a slow frame is paying for; a cheaper preset only bought jaggies. */
    smaaPreset: SMAAPreset.ULTRA,
    outline: true,
    outlineResolutionScale: 0.5,
    envSize: 128,
    ...SCENE_DETAIL,
  }),
  low: Object.freeze({
    tier: "low",
    /* Was 1. On a DPR 2 display that rendered a quarter of the pixels and let the browser scale the
       frame up: MEASURED (C5 critic, deviceScaleFactor 2, real GPU) a 1-px cable edge became a 4-5
       px ramp, the dark gap between a bridge's two strands never got back to background (201 vs
       12), and the lid louvers wobbled. Performance at this tier is bought with SSAO, bloom and
       outlines, which are off — never with resolution below MIN_PIXEL_RATIO. */
    maxPixelRatio: 2,
    /* Full resolution. This was 0.75, which rendered the frame at 75 % and upsampled it: every
       cable, chassis edge and floor line smeared uniformly (measured in one link region: 1058
       intermediate-luma pixels at low vs 629 at high, 415 full-coverage core pixels vs 541). That
       is blur standing in for anti-aliasing. At this tier the scene is ~28 draw calls and 57-89k
       triangles with SSAO, bloom and outlines already off — fill rate is not what a 25 % area cut
       was buying back. No resolution lever is left below native (up to DPR 2): see MIN_PIXEL_RATIO. */
    renderScale: 1,
    // Shadows off rather than bad: a 512px map over this scene's ~330-unit span gives detached,
    // blocky contact shadows, which read as a defect. The contact-shadow decals in
    // geometry/ground.ts ground every chassis without a shadow map, so nothing floats here.
    shadows: false,
    shadowMapSize: 512,
    ssao: false,
    ssaoSamples: 9,
    ssaoRings: 5,
    ssaoResolutionScale: 0.5,
    bloom: false,
    bloomLevels: 3,
    smaa: true,
    smaaPreset: SMAAPreset.ULTRA,
    outline: false,
    outlineResolutionScale: 0.5,
    envSize: 64,
    ...SCENE_DETAIL,
  }),
});

export function profileFor(tier: QualityTier): QualityProfile {
  return PROFILES[tier];
}

/**
 * The floor under the drawing-buffer resolution, at EVERY tier: min(devicePixelRatio, 2).
 *
 * It was 1.5, and 1.5 was the defect it claimed to prevent, one step removed: MEASURED (independent
 * audit C5, 2026-09-22, deviceScaleFactor 2, Intel iGPU) balanced and low drew a 2400x1350 buffer
 * for a 3200x1800 display, and the focused core1 chassis crop lost two thirds of its strong edges
 * (3679 -> 1267; gradient mean 9.0 -> 4.9) — the louvres and the port row visibly smeared, on the
 * tiers an iGPU user actually lands on. So every tier now draws at native resolution up to DPR 2,
 * and a tier buys its performance only with SSAO, bloom and outlines. A side effect worth having:
 * a tier change no longer reallocates the drawing buffer.
 *
 * The rule, not a per-tier constant, is what is guarded (`render-audit.test.tsx` sweeps every tier
 * against a range of display ratios): a buffer below this is upsampled by the compositor, and
 * upsampling is blur standing in for a cheaper frame. Both levers that could breach it — the DPR
 * cap and `renderScale` — met only in `effectivePixelRatio`, and the old guard pinned ONE of them on
 * ONE tier (`low.renderScale === 1`) while `low.maxPixelRatio` and `balanced.renderScale` produced
 * the same upsampling on every display above DPR 1.
 */
export const MIN_PIXEL_RATIO = 2;

/** The renderer pixel ratio a profile yields on a display — the ONE place the two levers meet. */
export function effectivePixelRatio(profile: QualityProfile, devicePixelRatio: number): number {
  const dpr = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  return Math.min(dpr, profile.maxPixelRatio) * profile.renderScale;
}

/**
 * What the status bar should say. `low` and `balanced` are always announced; `high` is announced
 * too, because "we are rendering everything" is itself information a screenshot reviewer needs.
 */
export function describeQuality(d: QualityDecision): string {
  const head = d.tier === "high" ? "full quality" : `reduced quality (${d.tier})`;
  const how = d.auto ? "auto-selected" : "set by the caller";
  return `${head}, ${how}: ${d.reasons.join("; ")}`;
}
