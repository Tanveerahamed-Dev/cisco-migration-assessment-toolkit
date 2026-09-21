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
  /** Ventilation slots and SFP cages are the first detail to go — sub-pixel at overview distance. */
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
    reasons.push(
      `software rasteriser detected (${caps.rendererName ?? "unnamed"}) — shadows and SSAO disabled`,
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
    `full quality: WebGL 2, ${caps.maxTextureSize}px textures, ${caps.maxAnisotropy}x anisotropy, ` +
      (caps.rendererName ?? UNKNOWN_RENDERER),
  );
  return { tier: "high", reasons, auto: true };
}

const PROFILES: Readonly<Record<QualityTier, QualityProfile>> = Object.freeze({
  high: Object.freeze({
    tier: "high",
    maxPixelRatio: 2,
    renderScale: 1,
    shadows: true,
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
    anisotropy: 8,
    cableSegments: 28,
    chassisBevelSegments: 3,
    chassisFineDetail: true,
  }),
  balanced: Object.freeze({
    tier: "balanced",
    maxPixelRatio: 1.5,
    renderScale: 0.85,
    shadows: true,
    shadowMapSize: 1024,
    ssao: true,
    ssaoSamples: 9,
    ssaoRings: 5,
    ssaoResolutionScale: 0.5,
    bloom: true,
    bloomLevels: 3,
    smaa: true,
    smaaPreset: SMAAPreset.HIGH,
    outline: true,
    outlineResolutionScale: 0.5,
    envSize: 128,
    anisotropy: 4,
    cableSegments: 20,
    chassisBevelSegments: 2,
    chassisFineDetail: true,
  }),
  low: Object.freeze({
    tier: "low",
    maxPixelRatio: 1,
    renderScale: 0.75,
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
    smaaPreset: SMAAPreset.MEDIUM,
    outline: false,
    outlineResolutionScale: 0.5,
    envSize: 64,
    anisotropy: 1,
    cableSegments: 14,
    chassisBevelSegments: 1,
    chassisFineDetail: false,
  }),
});

export function profileFor(tier: QualityTier): QualityProfile {
  return PROFILES[tier];
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
