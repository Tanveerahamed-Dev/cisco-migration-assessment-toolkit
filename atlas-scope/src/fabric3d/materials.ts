/**
 * materials.ts — the token bridge, the procedural texture generator, and the material library.
 *
 * Three jobs, deliberately in one file because they are one decision. A material's colour comes
 * from a CSS custom property (never a literal), its micro-surface comes from a procedurally
 * generated map (never a uniform value, which is the single most reliable tell of a cheap render),
 * and both are validated against the authoring bands in design-brief.md §4.6 before the material
 * is allowed out of the factory.
 *
 * Determinism: every texture here is generated from an integer hash, never `Math.random()`. Two
 * runs produce byte-identical pixels, which is what makes acceptance F6 (byte-identical captures)
 * achievable at all.
 */
import {
  BackSide,
  Color,
  DataTexture,
  LinearFilter,
  LinearMipmapLinearFilter,
  LinearSRGBColorSpace,
  MeshBasicMaterial,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  NoColorSpace,
  RGBAFormat,
  RepeatWrapping,
  SRGBColorSpace,
  ClampToEdgeWrapping,
  UnsignedByteType,
  type Material,
  type Texture,
} from "three";
import { agxInverse } from "./env";
import { own } from "../core/own";

/* ── token bridge ──────────────────────────────────────────────────────────── */

/**
 * The tokens the 3-D subsystem reads. Fallbacks are the amended values from design-brief.md §3.3
 * and exist for one reason: `src/core/tokens.css` is owned by another agent and does not yet
 * declare `--stage-bg` or the `--claim-*` family. A missing custom property resolves to the empty
 * string, and `Color.setStyle("")` would throw or silently leave the colour white — either way the
 * render would be wrong with no error. The fallback is the contract's own published value, so when
 * the token file catches up nothing moves.
 */
const TOKEN_FALLBACK_DARK: Readonly<Record<string, string>> = Object.freeze({
  "--stage-bg": "#0a0d13",
  "--bg": "#080a0e",
  "--surface-1": "#0d1117",
  "--surface-2": "#131923",
  "--surface-3": "#1b2330",
  "--text": "#e8ecf2",
  "--text-muted": "#96a1b2",
  "--accent": "#3fd0c9",
  "--focus": "#5aa8ff",
  "--sev-critical": "#ff6b6b",
  "--sev-high": "#ff9f45",
  "--sev-medium": "#f2cc4a",
  "--sev-low": "#6fb3ef",
  "--sev-info": "#96a1b2",
  "--state-up": "#47d18a",
  "--state-down": "#ff6b6b",
  "--state-unknown": "#a99bdc",
  "--band-excellent": "#47d18a",
  "--band-good": "#8bd45f",
  "--band-fair": "#f2cc4a",
  "--band-poor": "#ff9f45",
  "--band-critical": "#ff6b6b",
  "--claim-observed": "#96a1b2",
  "--claim-scoped": "#6fb3ef",
  "--claim-indeterminate": "#a99bdc",
  "--claim-out-of-scope": "#61728f",
  "--link-bridge": "#e879dc",
});

const TOKEN_FALLBACK_LIGHT: Readonly<Record<string, string>> = Object.freeze({
  "--stage-bg": "#eef1f5",
  "--bg": "#ffffff",
  "--surface-1": "#f7f8fa",
  "--surface-2": "#eef0f4",
  "--surface-3": "#e4e7ec",
  "--text": "#11151c",
  "--text-muted": "#4e5768",
  "--accent": "#0b6f68",
  "--focus": "#0b6bd3",
  "--sev-critical": "#b52626",
  "--sev-high": "#a14a0a",
  "--sev-medium": "#7a5d00",
  "--sev-low": "#275f8c",
  "--sev-info": "#4e5768",
  "--state-up": "#1b6d3d",
  "--state-down": "#b52626",
  "--state-unknown": "#6b5c99",
  "--band-excellent": "#1b6d3d",
  "--band-good": "#3f7733",
  "--band-fair": "#7a5d00",
  "--band-poor": "#a14a0a",
  "--band-critical": "#b52626",
  "--claim-observed": "#4e5768",
  "--claim-scoped": "#275f8c",
  "--claim-indeterminate": "#6b5c99",
  "--claim-out-of-scope": "#7f8899",
  "--link-bridge": "#9c1f8f",
});

export type ThemeName = "dark" | "light";

export interface TokenPalette {
  theme: ThemeName;
  /** Raw CSS strings, keyed by custom-property name including the leading `--`. */
  css: Readonly<Record<string, string>>;
  /** The same values as three Colors in the working (linear) space. */
  color(token: string): Color;
  /** Tokens that fell back because the stylesheet did not declare them. Surfaced, never hidden. */
  missing: string[];
}

/**
 * Read the palette out of the live stylesheet. Called at construction and on every theme change;
 * never per frame — `getComputedStyle` forces style resolution and belongs nowhere near the loop.
 */
export function readTokens(theme: ThemeName, root?: Element): TokenPalette {
  const fallback = theme === "dark" ? TOKEN_FALLBACK_DARK : TOKEN_FALLBACK_LIGHT;
  const el = root ?? (typeof document === "undefined" ? null : document.documentElement);
  const computed = el === null ? null : getComputedStyle(el);

  const css: Record<string, string> = {};
  const missing: string[] = [];
  for (const key of Object.keys(fallback)) {
    const live = computed === null ? "" : computed.getPropertyValue(key).trim();
    const fb = own(fallback, key) ?? "#ff00ff";
    if (live === "") {
      missing.push(key);
      css[key] = fb;
    } else {
      css[key] = live;
    }
  }

  const cache = new Map<string, Color>();
  return {
    theme,
    css,
    missing,
    color(token: string): Color {
      const hit = cache.get(token);
      if (hit !== undefined) return hit;
      const raw = own(css, token) ?? own(fallback, token) ?? "#ff00ff";
      // setStyle converts sRGB → working space when ColorManagement is enabled. Never setHex on a
      // literal read from CSS: that injects an sRGB value as a raw linear number (brief §4.3.5).
      const c = new Color().setStyle(raw);
      cache.set(token, c);
      return c;
    },
  };
}

/** Mix two token colours in the working space. Used for surface "stepping" (e.g. ground vs stage). */
export function mixTokens(a: Color, b: Color, t: number, out: Color): Color {
  return out.copy(a).lerp(b, t);
}

/* ── deterministic procedural textures ─────────────────────────────────────── */

/** 32-bit integer hash. Same input, same output, on every machine and every run. */
function hash2(x: number, y: number, seed: number): number {
  let h = (x * 374761393 + y * 668265263 + seed * 2246822519) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

const smootherstep = (t: number): number => t * t * t * (t * (t * 6 - 15) + 10);

/** Tiling value noise. Tiles because the lattice is taken modulo `period` — seams are a tell. */
function valueNoise(x: number, y: number, period: number, seed: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = smootherstep(x - xi);
  const yf = smootherstep(y - yi);
  const m = (v: number): number => ((v % period) + period) % period;
  const x0 = m(xi);
  const x1 = m(xi + 1);
  const y0 = m(yi);
  const y1 = m(yi + 1);
  const n00 = hash2(x0, y0, seed);
  const n10 = hash2(x1, y0, seed);
  const n01 = hash2(x0, y1, seed);
  const n11 = hash2(x1, y1, seed);
  const a = n00 + (n10 - n00) * xf;
  const b = n01 + (n11 - n01) * xf;
  return a + (b - a) * yf;
}

function fbm(x: number, y: number, basePeriod: number, octaves: number, seed: number): number {
  let sum = 0;
  let amp = 1;
  let norm = 0;
  let period = basePeriod;
  let freq = 1;
  for (let o = 0; o < octaves; o += 1) {
    sum += amp * valueNoise(x * freq, y * freq, period, seed + o * 101);
    norm += amp;
    amp *= 0.5;
    freq *= 2;
    period *= 2;
  }
  return norm === 0 ? 0 : sum / norm;
}

function makeTexture(size: number, data: Uint8Array, wrap: boolean, anisotropy: number): DataTexture {
  const tex = new DataTexture(data, size, size, RGBAFormat, UnsignedByteType);
  // Data textures carry measurements, not colour. Tagging them sRGB would apply a transfer
  // function to a roughness value — the classic silent render bug (brief §4.3.4).
  tex.colorSpace = NoColorSpace;
  tex.wrapS = wrap ? RepeatWrapping : ClampToEdgeWrapping;
  tex.wrapT = wrap ? RepeatWrapping : ClampToEdgeWrapping;
  tex.magFilter = LinearFilter;
  tex.minFilter = LinearMipmapLinearFilter;
  tex.generateMipmaps = true;
  tex.anisotropy = anisotropy;
  tex.needsUpdate = true;
  return tex;
}

function withChannel(tex: DataTexture, channel: number): DataTexture {
  tex.channel = channel;
  return tex;
}

export interface ProceduralMaps {
  /** R = ambient occlusion, G = roughness multiplier, B = metalness multiplier (held at 1). */
  chassisOrm: DataTexture;
  /** Finer, streaked along X — brushed metal for the faceplate. */
  bezelOrm: DataTexture;
  /** Tangent-space normal carrying the brushing and a little casting grain. */
  chassisNormal: DataTexture;
  /** 45-degree stripes in alpha. The "not collected" hatch; never a colour, never an absence. */
  hatch: DataTexture;
  /** Radial falloff in alpha — the ground's edge fade and the selection halo. */
  radialFade: DataTexture;
  /**
   * The contact-shadow falloff, which is NOT `radialFade` and must never be folded back into it.
   *
   * MEASURED 2026-09-21: with `radialFade` on the contact decal the fabric had no grounding at all.
   * `radialFade` peaks at the decal's CENTRE — which is the one part of the decal a chassis
   * standing on it hides completely. The decal is 1.8x the chassis half-extent, so the chassis
   * silhouette sits at normalised radius ~0.51-0.76 and only the outer, weakest tail of the fade
   * is ever visible: (1 - 0.555)^2.2 * 0.52 = 0.086 alpha at the near edge, an 8 % darkening of a
   * near-black deck. Turning the decal red and opaque showed the ellipse IS drawn; forcing its
   * alpha to 1 moved 6 of 80 deck samples. A grounding cue that is strongest where it cannot be
   * seen is not a grounding cue.
   *
   * This one is a PLATEAU: opaque out to `CONTACT_PLATEAU`, then a smoothstep to nothing at the
   * decal edge. The plateau is sized to end just inside the silhouette, so the alpha is still ~0.9
   * where the chassis meets its deck — a real contact shadow — and falls to zero well before the
   * decal's own boundary, so it never terminates on a visible ellipse.
   */
  contactFade: DataTexture;
  /** Faint rectilinear grid plus a roughness break-up for the ground plane. */
  groundOrm: DataTexture;
  /**
   * The port grille, one tile per port, sRGB albedo multiplied into the bezel colour on UV
   * channel 1 (geometry/chassis.ts). White where the tile is bar metal, dark in the opening, a
   * mid-tone contact block inside it. It replaced a grid of sub-pixel bar GEOMETRY that aliased into
   * glyph-like shapes; the texture's mip chain is what makes the bank minify to a tone instead.
   */
  grille: DataTexture;
  dispose(): void;
}

/** Share of a deck/pad's alpha left when it is seen fully edge-on (see the deck's grazing fade). */
export const DECK_GRAZE_FLOOR = 0.12;
const ORM_SIZE = 256;
const NORMAL_SIZE = 256;
/** Height amplitude of the lid's low-frequency panel term — see `heightAt`.
 *  Halved from 20 (C5 critic, 2026-09-22: lids read as stained). The critic named the AO patina,
 *  and that was removed, but MEASURED it was not the cause: flat-lid patch std 3.97 -> 4.05 with the
 *  AO change alone (aoMap only scales indirect light). The blotches were this term's value-noise
 *  cells lit by the key. At 10 the same patch measures std 2.1 / range 150-165 (was 3.97 / 143-171)
 *  at both tiers, and the lid still carries a soft light-to-dark drift rather than flat paint. */
const PANEL_UNDULATION = 10;
/** Weight of the X-streaked grain in the chassis height field — see `heightAt`. */
const BODY_STREAK = 0.2;
const HATCH_SIZE = 128;
/** Half-width of the hatch stripe's edge ramp, in diagonal texel units (see the hatch generator). */
const HATCH_RAMP = 2;
function smooth01(e0: number, e1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}
const FADE_SIZE = 128;
/** Where the contact decal stops being fully opaque, in normalised decal radius. See contactFade. */
export const CONTACT_PLATEAU = 0.46;
const GROUND_SIZE = 512;
/** Texels per port tile. Enough that a port 60 px wide on screen still magnifies cleanly. */
export const GRILLE_SIZE = 64;
/** Bar metal as a fraction of the tile, per axis, half on each edge. */
const GRILLE_BAR_X = 0.26;
const GRILLE_BAR_Y = 0.24;
/**
 * Anisotropy floor for the grille. The bank is seen at grazing angles on every lower-tier chassis,
 * and anisotropic filtering is nearly free on any GPU that has it; the tier's own value applies
 * above this floor.
 */
export const GRILLE_MIN_ANISOTROPY = 8;

/** The grille tile, in sRGB bytes. Pure, so a test can check the metal corner is exactly white. */
export function grilleTile(): Uint8Array {
  const n = GRILLE_SIZE;
  const out = new Uint8Array(n * n * 4);
  const bx = (GRILLE_BAR_X / 2) * n;
  const by = (GRILLE_BAR_Y / 2) * n;
  for (let y = 0; y < n; y += 1) {
    for (let x = 0; x < n; x += 1) {
      const cx = x + 0.5;
      const cy = y + 0.5;
      // Distance into the opening from its nearest edge, in texels (negative = on the bar).
      const ix = Math.min(cx - bx, n - bx - cx);
      const iy = Math.min(cy - by, n - by - cy);
      let v: number;
      if (ix <= 0 || iy <= 0) {
        // Bar metal: multiplies the bezel colour by exactly 1. The bar's lower lip over each
        // opening is shaded (texture v runs bottom-up; the key light is above) — the one baked cue
        // that keeps a flat plate reading as a recess rather than a print.
        v = iy > -2 && ix > 0 && cy < n / 2 ? 200 : 255;
      } else {
        v = 34; // the opening
        // The shadow the upper bar throws into the opening.
        if (cy > n - by - 5) v = 22;
        // The contact block, 60 % x 44 % of the tile, centred, with a lit top edge.
        const kx = Math.abs(cx - n / 2) <= n * 0.3;
        const ky = Math.abs(cy - n / 2) <= n * 0.22;
        if (kx && ky) v = Math.abs(cy - (n / 2 + n * 0.22)) < 1.5 ? 120 : 82;
      }
      const i = (y * n + x) * 4;
      out[i] = v;
      out[i + 1] = v;
      out[i + 2] = v;
      out[i + 3] = 255;
    }
  }
  return out;
}

/**
 * Roughness is written as a MULTIPLIER in [0.78, 1.0] rather than an absolute value, because
 * `roughnessMap` multiplies `material.roughness`. Keeping the map below 1 and lifting the scalar
 * slightly means the product lands inside the authoring band while the surface still varies —
 * which is the whole point. A flat roughness is what makes a render look like plastic.
 */
/** The CPU-side bytes of every procedural map. Pure functions of constants, so computed once. */
interface ProceduralPixels {
  chassisOrm: Uint8Array;
  bezelOrm: Uint8Array;
  normal: Uint8Array;
  hatch: Uint8Array;
  fade: Uint8Array;
  contact: Uint8Array;
  ground: Uint8Array;
}

/**
 * The map bytes, generated one texel ROW per step.
 *
 * RESPONSIVENESS FIX, 2026-09-21 (acceptance E5). These loops used to run inside
 * `buildProceduralMaps`, which `createScene` calls synchronously from the stage's mount effect.
 * CPU profile of a cold navigation to the path surface on the dev build: createScene 1081 ms, of
 * which buildProceduralMaps was 811 ms (fbm noise over 256² + 256² + 256² x 4 taps + 512² texels).
 * That was the single blocking task the E5 sweep attributed to `MessagePort.onmessage` (531 ms
 * median on the release build) and the bulk of the cold-load frame no keystroke could get through.
 *
 * As a generator the same arithmetic, in the same order, produces the same bytes; it can simply be
 * stopped between rows. `prepareProceduralMaps` runs it against a deadline and yields to the event
 * loop between slices; `buildProceduralMaps` runs whatever is left synchronously, so a caller that
 * never prepared (a test, the capture harness) still gets identical maps.
 */
function* generateProceduralPixels(): Generator<void, ProceduralPixels, void> {
  const chassisOrm = new Uint8Array(ORM_SIZE * ORM_SIZE * 4);
  for (let y = 0; y < ORM_SIZE; y += 1) {
    for (let x = 0; x < ORM_SIZE; x += 1) {
      const u = (x / ORM_SIZE) * 8;
      const v = (y / ORM_SIZE) * 8;
      const grain = fbm(u * 3, v * 3, 24, 4, 17);
      /* PATINA IS ROUGHNESS ONLY (C5 critic, 2026-09-22). It used to drive the AO channel too
         (`ao = 0.82 + 0.18 * patina * seam`), at base period 8 — a low-frequency fbm that painted
         every lid with blotches reading as stains (flat lid patch L std 6.3, range 116-172 at both
         tiers). AO is occlusion, and a flat lid occludes nothing, so the channel now carries only the
         seam gutter. The break-up stays in roughness, at 4x the frequency, where it modulates the
         highlight instead of the albedo. */
      const patina = fbm(u * 4, v * 4, 32, 3, 91);
      // Panel-line darkening: a faint AO gutter every sixth of the texture, where a real chassis
      // has a seam between its top cover and its side panels.
      const seam = Math.min(1, Math.abs(((y / ORM_SIZE) * 6) % 1 - 0.5) * 7);
      const ao = 0.86 + 0.14 * seam;
      const rough = 0.78 + 0.22 * (0.65 * grain + 0.35 * patina);
      const i = (y * ORM_SIZE + x) * 4;
      chassisOrm[i] = Math.round(Math.min(1, ao) * 255);
      chassisOrm[i + 1] = Math.round(Math.min(1, rough) * 255);
      chassisOrm[i + 2] = 255;
      chassisOrm[i + 3] = 255;
    }
    yield;
  }

  const bezelOrm = new Uint8Array(ORM_SIZE * ORM_SIZE * 4);
  for (let y = 0; y < ORM_SIZE; y += 1) {
    for (let x = 0; x < ORM_SIZE; x += 1) {
      const u = (x / ORM_SIZE) * 64;
      const v = (y / ORM_SIZE) * 4;
      // Brushing: high frequency along X, almost none along Y. This is what anisotropy on the
      // physical material then stretches into a directional highlight.
      const brush = fbm(u, v * 0.15, 64, 3, 311);
      const rough = 0.84 + 0.16 * brush;
      const i = (y * ORM_SIZE + x) * 4;
      bezelOrm[i] = 240;
      bezelOrm[i + 1] = Math.round(Math.min(1, rough) * 255);
      bezelOrm[i + 2] = 255;
      bezelOrm[i + 3] = 255;
    }
    yield;
  }

  const normal = new Uint8Array(NORMAL_SIZE * NORMAL_SIZE * 4);
  const heightAt = (x: number, y: number): number => {
    const u = (x / NORMAL_SIZE) * 48;
    const v = (y / NORMAL_SIZE) * 48;
    /* The PANEL term: a broad, low-frequency undulation, 2 cells per tile (~5 across a lid). The
       two fine terms are grain — at 5 texels a cell they average to one normal at any distance the
       camera can reach, and the lid measured as flat paint (C5 critic: core1 at maximum dolly, DPR
       2, lid luma std 0.91; reproduced 2026-09-22 at std 0.90). A sheet-steel lid is never optically
       flat: its powder coat and pressing put long, soft tilts in it, which the key light turns
       into a gentle light-to-dark drift across the face. That drift is what reads as a lit
       surface rather than a fill colour. Amplitude is set in slope, not height: ~3 degrees of tilt
       after the body's normalScale (halved 2026-09-22, see PANEL_UNDULATION) without making it
       read as dented. Exercised by the lid probe; not a colour change, so bands and tokens are
       untouched. */
    const panel = PANEL_UNDULATION * fbm(u / 24, v / 24, 2, 1, 919);
    /* The STREAK term (fbm stretched 5:1 along X) is cut from 0.6 to 0.2: MEASURED (independent
       audit C5, 2026-09-22, deep/z_onebox.png, z_grazing.png) at close range it read as a streaky,
       wood-grain-like noise across every chassis face. The panel drift above is what makes the lid
       read as lit; the streaks only made it read as timber. */
    return BODY_STREAK * fbm(u, v * 0.2, 48, 3, 733) + 0.4 * fbm(u * 0.5, v * 0.5, 24, 4, 127) + panel;
  };
  const BUMP = 1.35;
  for (let y = 0; y < NORMAL_SIZE; y += 1) {
    for (let x = 0; x < NORMAL_SIZE; x += 1) {
      const w = (v: number): number => ((v % NORMAL_SIZE) + NORMAL_SIZE) % NORMAL_SIZE;
      const dx = (heightAt(w(x + 1), y) - heightAt(w(x - 1), y)) * BUMP;
      const dy = (heightAt(x, w(y + 1)) - heightAt(x, w(y - 1))) * BUMP;
      const len = Math.hypot(dx, dy, 1);
      const i = (y * NORMAL_SIZE + x) * 4;
      normal[i] = Math.round(((-dx / len) * 0.5 + 0.5) * 255);
      normal[i + 1] = Math.round(((-dy / len) * 0.5 + 0.5) * 255);
      normal[i + 2] = Math.round((1 / len) * 0.5 * 255 + 127.5);
      normal[i + 3] = 255;
    }
    yield;
  }

  const hatch = new Uint8Array(HATCH_SIZE * HATCH_SIZE * 4);
  for (let y = 0; y < HATCH_SIZE; y += 1) {
    for (let x = 0; x < HATCH_SIZE; x += 1) {
      // 45 degrees exactly, so it never aligns with a chassis edge and never reads as geometry.
      /* ANTI-ALIASED IN THE TEXTURE. The stripe edge used to fall off over ~1 texel (a 64² map, a
         16-texel period, `edge * 14`), so the coverage was effectively binary per texel and, when
         the camera dollies in far enough to MAGNIFY the map, linear filtering between those binary
         texels drew each 45-degree edge as a staircase — MEASURED (C5 critic, AP-floor1 dollied
         in, both tiers). Now 128² with the same four stripes per tile (period 32 texels) and a
         smoothstep ramp ~2.8 texels wide across each edge, so magnified edges interpolate a real
         gradient; minified, the mip chain averages it as before. `u` is measured along the
         diagonal, so HATCH_RAMP of 2 is 2 / sqrt 2 texels either side of the edge. */
      const period = HATCH_SIZE / 4;
      const duty = period * 0.32;
      const u = (x + y + 1) % period;
      let cover = 0;
      for (const w of [u - period, u, u + period]) {
        cover = Math.max(cover, smooth01(-HATCH_RAMP, HATCH_RAMP, w) * (1 - smooth01(duty - HATCH_RAMP, duty + HATCH_RAMP, w)));
      }
      const a = Math.round(cover * 255);
      const i = (y * HATCH_SIZE + x) * 4;
      // The coverage goes in EVERY channel, green included. three's alphamap_fragment samples
      // `.g`, not `.a` — a mask written only into alpha compiles, binds, renders, and does
      // absolutely nothing, with no warning at any layer.
      hatch[i] = a;
      hatch[i + 1] = a;
      hatch[i + 2] = a;
      hatch[i + 3] = a;
    }
    yield;
  }

  const fade = new Uint8Array(FADE_SIZE * FADE_SIZE * 4);
  for (let y = 0; y < FADE_SIZE; y += 1) {
    for (let x = 0; x < FADE_SIZE; x += 1) {
      const nx = (x + 0.5) / FADE_SIZE - 0.5;
      const ny = (y + 0.5) / FADE_SIZE - 0.5;
      const r = Math.min(1, Math.hypot(nx, ny) * 2);
      // Squared falloff, then smoothed: a linear falloff has a visible terminating ring.
      const a = Math.round(Math.max(0, Math.min(1, Math.pow(1 - r, 2.2))) * 255);
      const i = (y * FADE_SIZE + x) * 4;
      // Green channel carries the mask (see the hatch above); the rest match so the same texture
      // can also be read as a plain luminance map if it is ever wanted as one.
      fade[i] = a;
      fade[i + 1] = a;
      fade[i + 2] = a;
      fade[i + 3] = a;
    }
    yield;
  }

  /* The contact-shadow falloff. See ProceduralMaps.contactFade for why this is not `fade`.

     `r` is normalised so that r = 1 at the decal's own edge (hypot * 2 over a 0..1 quad). The
     chassis silhouette lands between r = 0.51 (edge midpoint) and r = 0.76 (corner) at the decal
     scale ground.ts uses, so the plateau ends at 0.46: full strength everywhere the chassis hides,
     still ~0.92 where the chassis meets the deck, zero by the decal boundary. */
  const contact = new Uint8Array(FADE_SIZE * FADE_SIZE * 4);
  for (let y = 0; y < FADE_SIZE; y += 1) {
    for (let x = 0; x < FADE_SIZE; x += 1) {
      const nx = (x + 0.5) / FADE_SIZE - 0.5;
      const ny = (y + 0.5) / FADE_SIZE - 0.5;
      const r = Math.min(1, Math.hypot(nx, ny) * 2);
      // smoothstep from the plateau edge outward: C1-continuous at both ends, so neither the
      // plateau boundary nor the outer edge leaves a terminating ring.
      const t = Math.max(0, Math.min(1, (1 - r) / (1 - CONTACT_PLATEAU)));
      const a = Math.round(t * t * (3 - 2 * t) * 255);
      const i = (y * FADE_SIZE + x) * 4;
      // Coverage in every channel — three's alphamap_fragment samples `.g`, not `.a`.
      contact[i] = a;
      contact[i + 1] = a;
      contact[i + 2] = a;
      contact[i + 3] = a;
    }
    yield;
  }

  const ground = new Uint8Array(GROUND_SIZE * GROUND_SIZE * 4);
  for (let y = 0; y < GROUND_SIZE; y += 1) {
    for (let x = 0; x < GROUND_SIZE; x += 1) {
      const u = (x / GROUND_SIZE) * 6;
      const v = (y / GROUND_SIZE) * 6;
      const grain = fbm(u * 2, v * 2, 12, 4, 55);
      const gx = Math.abs(((x / GROUND_SIZE) * 8) % 1 - 0.5);
      const gy = Math.abs(((y / GROUND_SIZE) * 8) % 1 - 0.5);
      // Grid as an AO dip rather than a colour line: it survives tone mapping without becoming a
      // bright stripe, and it cannot turn into a moire fence because mipmaps average it away.
      const grid = Math.min(1, Math.min(gx, gy) * 26 + 0.86);
      const i = (y * GROUND_SIZE + x) * 4;
      ground[i] = Math.round(Math.min(1, grid * (0.9 + 0.1 * grain)) * 255);
      ground[i + 1] = Math.round(Math.min(1, 0.86 + 0.14 * grain) * 255);
      ground[i + 2] = 255;
      ground[i + 3] = 255;
    }
    yield;
  }

  return { chassisOrm, bezelOrm, normal, hatch, fade, contact, ground };
}

let pixelCache: ProceduralPixels | null = null;
let pixelJob: Generator<void, ProceduralPixels, void> | null = null;
let preparing: Promise<void> | null = null;

/**
 * Advance the shared job by at most `rows` texel rows, or to completion. True when done.
 *
 * Sliced by WORK, not by a clock: the same rows in the same order whatever the slice size, so the
 * bytes are identical to an unsliced run, and there is no clock read here for the determinism gate
 * to have to take on trust.
 */
function stepPixels(rows: number): boolean {
  if (pixelCache) return true;
  pixelJob ??= generateProceduralPixels();
  for (let i = 0; ; i += 1) {
    const r = pixelJob.next();
    if (r.done === true) {
      pixelCache = r.value;
      pixelJob = null;
      return true;
    }
    if (i + 1 >= rows) return false;
  }
}

/** True once the procedural map bytes exist, so a scene can be built without generating them. */
export function proceduralMapsReady(): boolean {
  return pixelCache !== null;
}

/**
 * Rows per slice. A row is 64-512 texels of fbm noise. CPU profile on the DEV build: the heaviest
 * rows (the 256-wide normal map, four height taps per texel) cost about 1.3 ms each, so 8 rows keeps
 * a slice well under the 50 ms task ceiling (design-brief §8.3 rule 1) — a keystroke that lands during
 * the cold load waits at most one slice.
 */
const PREPARE_SLICE_ROWS = 8;

/**
 * Generate the procedural map bytes off the critical path: PREPARE_SLICE_ROWS rows at a time,
 * yielding to the event loop between slices. Idempotent; every caller shares one job.
 *
 * Yield: `scheduler.yield()` where it exists, which resumes AHEAD of other queued tasks. The
 * fallback, a Promise-wrapped `setTimeout(..., 0)`, re-queues at the BACK of the task queue and
 * can be preempted by unrelated tasks — slower to finish, never less responsive. The two are not
 * equivalent and this note is where that is said (design-brief §8.3 rule 1).
 */
export function prepareProceduralMaps(): Promise<void> {
  if (pixelCache) return Promise.resolve();
  preparing ??= (async () => {
    const sched = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
    const yieldNow = (): Promise<void> =>
      typeof sched?.yield === "function"
        ? sched.yield()
        : new Promise<void>((resolve) => {
            setTimeout(resolve, 0);
          });
    while (!stepPixels(PREPARE_SLICE_ROWS)) await yieldNow();
  })();
  return preparing;
}

export function buildProceduralMaps(anisotropy: number): ProceduralMaps {
  stepPixels(Number.POSITIVE_INFINITY);
  const { chassisOrm, bezelOrm, normal, hatch, fade, contact, ground } = pixelCache as ProceduralPixels;
  const maps: ProceduralMaps = {
    chassisOrm: makeTexture(ORM_SIZE, chassisOrm, true, anisotropy),
    bezelOrm: makeTexture(ORM_SIZE, bezelOrm, true, anisotropy),
    chassisNormal: makeTexture(NORMAL_SIZE, normal, true, anisotropy),
    hatch: makeTexture(HATCH_SIZE, hatch, true, 1),
    radialFade: makeTexture(FADE_SIZE, fade, false, 1),
    contactFade: makeTexture(FADE_SIZE, contact, false, 1),
    // Channel 1: the ground and deck geometries carry a tiled second UV set so their surface
    // detail can repeat while UV0 stays 0..1 for the radial alpha fade. One texture, two jobs.
    groundOrm: withChannel(makeTexture(GROUND_SIZE, ground, true, anisotropy), 1),
    grille: (() => {
      const t = withChannel(
        makeTexture(GRILLE_SIZE, grilleTile(), true, Math.max(GRILLE_MIN_ANISOTROPY, anisotropy)),
        1,
      );
      // Unlike every other map here this one IS colour (an albedo multiplier), so it is sRGB.
      t.colorSpace = SRGBColorSpace;
      return t;
    })(),
    dispose(): void {
      for (const t of [
        maps.chassisOrm,
        maps.bezelOrm,
        maps.chassisNormal,
        maps.hatch,
        maps.radialFade,
        maps.contactFade,
        maps.groundOrm,
        maps.grille,
      ]) {
        t.dispose();
      }
    },
  };
  return maps;
}

/* ── the emphasis channel ──────────────────────────────────────────────────── */

/**
 * Per-instance emphasis in [0,1]: 1 = fully present, 0 = fully receded.
 *
 * Receding is desaturate + dim, never hide. Hiding off-path structure produces a picture that
 * cannot be checked — you can no longer see the alternate link that should have been taken
 * (design-brief.md §4.5). The floor below is therefore a floor, not a fade to nothing.
 */
export const EMPHASIS_FLOOR = 0.28;

/**
 * The attribute stores RECESSION, not emphasis, and 0 means "fully present".
 *
 * The inversion is a safety property, not a style choice: an attribute a geometry forgot to declare
 * is read by WebGL as zero. Under "emphasis" semantics that mistake would recede the entire mesh —
 * a silent, whole-scene visual failure with no error anywhere. Under "recession" semantics the same
 * mistake renders correctly.
 */
export const RECEDE_ATTRIBUTE = "aRecede";

const EMPHASIS_VERT_DECL = `
attribute float aRecede;
varying float vRecede;
`;

const EMPHASIS_FRAG_DECL = `
varying float vRecede;
uniform vec3 uRecedeTarget;
uniform float uRecedeMix;
`;

/*
 * Recession has to be MEASURABLY strong on achromatic hardware.
 *
 * Desaturation alone does nothing to a grey chassis, so the visible work is done by the dim term:
 * at the 0.62 recession the scene uses for "something else is the subject", presence drops to
 * about 0.41 — which is the brief's "non-matching nodes drop to 35 % chassis" rendered as
 * radiance rather than as alpha, so an opaque material honours it too. It never reaches zero: the
 * alternate path you can no longer see is the one you needed.
 */
const EMPHASIS_FRAG_APPLY = `
{
  float r = clamp(vRecede, 0.0, 1.0);
  float lum = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
  diffuseColor.rgb = mix(diffuseColor.rgb, vec3(lum), r);
  diffuseColor.a *= 1.0 - r * 0.45;
}
`;

/**
 * The dim is applied to the FINAL radiance, not to the albedo, and it recedes TOWARD THE STAGE.
 *
 * Dimming `diffuseColor` alone leaves a receded dielectric with its full specular and full
 * image-based reflection, so a chassis that is supposed to be context keeps a bright highlight and
 * goes on competing for attention. Blending `gl_FragColor` just before the colour-space conversion
 * catches diffuse, specular, environment and emissive in one place.
 *
 * It used to MULTIPLY toward black (`*= 1 - r * 0.8`). On the dark stage that is a recession; on
 * the light stage it is the opposite — a darker chassis on a near-white ground gains contrast and
 * pulls MORE attention — and in measurement it barely registered (render audit: selecting core1
 * moved a neighbouring chassis 3 % in luma, a non-neighbour 9-13 % in light). The target is now the
 * stage as the post chain will display it: `uRecedeTarget` is the AgX pre-image of `--stage-bg`
 * (env.ts `agxInverse`, set per theme by `retintMaterials`), so recession converges on the
 * backdrop in both themes. `RECEDE_MIX` < 1 keeps it from ever arriving: the alternate path you can
 * no longer see is the one you needed.
 */
/** Per theme: the light target is an HDR pre-image several times brighter than any lit chassis, so
 *  the same linear blend reads far stronger there. Tuned by measurement, see `retintMaterials`. */
export const RECEDE_MIX = { dark: 0.85, light: 0.15 } as const;
/** Shared by every emphasis-patched program; `retintMaterials` writes it per theme. */
const recedeTarget = { value: new Color(0, 0, 0) };
const recedeMix = { value: RECEDE_MIX.dark as number };
const EMPHASIS_FRAG_DIM = `
gl_FragColor.rgb = mix(gl_FragColor.rgb, uRecedeTarget, clamp(vRecede, 0.0, 1.0) * uRecedeMix);
`;

/**
 * Patch a standard-lit material so it honours the per-instance `aEmphasis` attribute. Applied via
 * onBeforeCompile so the material keeps every three.js feature (shadows, env map, tone mapping)
 * instead of being replaced by a hand-written shader that would have to re-implement all of it.
 *
 * `emissiveFromInstanceColor` additionally routes the instance colour into emissive radiance,
 * which is how one InstancedMesh of status LEDs can emit a different colour per device without a
 * material per device.
 */
/**
 * Route the per-instance colour into emissive radiance — guarded by the SAME condition three.js
 * uses to declare the varying.
 *
 * This was previously injected unguarded, and the whole fabric rendered as a black screen. The
 * varying `vColor` is declared by `color_pars_fragment` only under
 * `USE_COLOR || USE_COLOR_ALPHA || USE_INSTANCING_COLOR || USE_BATCHING_COLOR`; three sets
 * `USE_INSTANCING_COLOR` when an InstancedMesh actually carries an `instanceColor`, which is not
 * true at every compile. When it was not, the fragment shader failed to compile with
 * "'vColor' : undeclared identifier" and every mesh using the material silently drew nothing.
 *
 * Two things make that failure especially worth guarding against:
 *   - GL reports it to the console and then carries on. `renderer.info` still reported 28 draw
 *     calls and 56k triangles against a blank canvas, so the scene's own stats said healthy.
 *   - It is invisible to `scene.test.ts` by construction: jsdom has no GL, so no shader is ever
 *     compiled there. The suite was green throughout.
 *
 * Mirroring three's own condition — rather than picking the one define we expect — means the
 * injection cannot disagree with the declaration no matter how the mesh is built.
 */
const EMISSIVE_FROM_COLOR = `
#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
  totalEmissiveRadiance *= vColor.rgb;
#endif`;

export function withEmphasis<M extends MeshStandardMaterial>(
  material: M,
  opts: { emissiveFromInstanceColor?: boolean } = {},
): M {
  const emissiveFromColor = opts.emissiveFromInstanceColor === true;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uRecedeTarget = recedeTarget;
    shader.uniforms.uRecedeMix = recedeMix;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>${EMPHASIS_VERT_DECL}`)
      .replace("#include <begin_vertex>", "#include <begin_vertex>\n  vRecede = aRecede;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>${EMPHASIS_FRAG_DECL}`)
      .replace("#include <color_fragment>", `#include <color_fragment>${EMPHASIS_FRAG_APPLY}`)
      .replace("#include <colorspace_fragment>", `${EMPHASIS_FRAG_DIM}#include <colorspace_fragment>`)
      .replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>\n  totalEmissiveRadiance *= mix(0.18, 1.0, 1.0 - clamp(vRecede, 0.0, 1.0));` +
          (emissiveFromColor ? EMISSIVE_FROM_COLOR : ""),
      );
  };
  // Distinguishes the two shader variants in three's program cache. Without this, a material that
  // routes instance colour into emissive could be handed the program compiled for one that does not.
  material.customProgramCacheKey = () => `atlas-emphasis:${emissiveFromColor ? "emissive" : "plain"}`;
  return material;
}

/**
 * Screen pixels per grille tile below which the tile's pattern is faded to its mean tone, and the
 * width of that fade. See `withGrilleNyquistFade`.
 */
export const GRILLE_FADE_PX: readonly [number, number] = [2.5, 5];

/**
 * Fade the grille map (ports and lid vents, one tile per opening) to its own MEAN tone as a tile
 * approaches the pixel grid.
 *
 * A mip chain alone does not do this. Trilinear filtering picks the level whose texel is about one
 * pixel, and at that level a 64-texel tile is still a 2-texel light/dark pattern — i.e. a period of
 * about two pixels, exactly the Nyquist limit — so a vent bank of 16 slots at the overview still
 * beat against the pixel grid as faint diagonal bars that turned with a 3 px orbit (MEASURED
 * 2026-09-22 after the vents moved from geometry onto this map: the bars' contrast fell ~4x but
 * their direction still changed frame to frame at both tiers). So the pattern is blended out by
 * its screen-space size, from the UV derivatives: full detail above GRILLE_FADE_PX[1] pixels per
 * tile, the smallest mip (the tile's average) at GRILLE_FADE_PX[0] and below. The constant-UV metal
 * parts have zero derivatives, so they are never touched.
 */
export function withGrilleNyquistFade<M extends MeshStandardMaterial>(material: M): M {
  const inner = material.onBeforeCompile;
  const innerKey = material.customProgramCacheKey.bind(material);
  const [lo, hi] = GRILLE_FADE_PX;
  material.onBeforeCompile = (shader, renderer) => {
    inner.call(material, shader, renderer);
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <map_fragment>",
      `#ifdef USE_MAP
  vec4 sampledDiffuseColor = texture2D( map, vMapUv );
  float _tileW = max( length( dFdx( vMapUv ) ), length( dFdy( vMapUv ) ) );
  float _pxPerTile = _tileW > 1e-6 ? 1.0 / _tileW : 1e6;
  float _grilleFade = 1.0 - smoothstep( ${lo.toFixed(2)}, ${hi.toFixed(2)}, _pxPerTile );
  sampledDiffuseColor = mix( sampledDiffuseColor, textureLod( map, vMapUv, 12.0 ), _grilleFade );
  diffuseColor *= sampledDiffuseColor;
#endif`,
    );
  };
  material.customProgramCacheKey = () => `${innerKey()}|grille-nyquist`;
  return material;
}

/* ── authoring-band enforcement ────────────────────────────────────────────── */

export interface BandViolation {
  material: string;
  property: string;
  value: number;
  allowed: string;
}

/**
 * design-brief.md §4.6: metalness is binary, roughness lives in a band, and neither pure black nor
 * pure white exists as a dielectric albedo. Run at construction, reported rather than thrown in
 * production — a render that is slightly wrong is better than a blank canvas — but the scene
 * throws on it in dev so it can never be shipped unnoticed.
 */
export function checkAuthoringBands(materials: Iterable<Material>): BandViolation[] {
  const out: BandViolation[] = [];
  for (const m of materials) {
    if (!(m instanceof MeshStandardMaterial)) continue;
    const name = m.name === "" ? m.type : m.name;
    const metal = m.metalness;
    if (metal !== 0 && metal !== 1) {
      out.push({ material: name, property: "metalness", value: metal, allowed: "0 or 1" });
    }
    const lo = metal === 1 ? 0.15 : 0.25;
    const hi = metal === 1 ? 0.45 : 0.9;
    if (m.roughness < lo || m.roughness > hi) {
      out.push({ material: name, property: "roughness", value: m.roughness, allowed: `[${lo}, ${hi}]` });
    }
    if (metal === 0) {
      // Measured in sRGB, which is the space design-brief.md §4.6 states the band in. Checking the
      // linear value instead would silently move the ceiling by a factor of ~1.14 and let a near-
      // white dielectric through — and neither pure black nor pure white exists in a real material.
      const srgb = m.color.clone().convertLinearToSRGB();
      const l = 0.2126 * srgb.r + 0.7152 * srgb.g + 0.0722 * srgb.b;
      if (l < 0.03 || l > 0.9) {
        out.push({ material: name, property: "albedo luminance", value: l, allowed: "[0.03, 0.9] sRGB" });
      }
    }
  }
  return out;
}

/* ── the material library ──────────────────────────────────────────────────── */

/*
 * A note on per-instance colour, because getting it wrong is silent and total.
 *
 * NONE of the materials below set `vertexColors: true`, and that is deliberate. Per-instance
 * colour arrives through `InstancedMesh.setColorAt`, which makes three define
 * `USE_INSTANCING_COLOR` and declare the `vColor` varying on its own. Setting `vertexColors` as
 * well would additionally define `USE_COLOR`, whose vertex shader declares `attribute vec3 color`
 * and multiplies `vColor` by it — and there IS no `color` attribute on these geometries, so the
 * multiply reads a generic attribute whose value is driver-dependent and typically zero. The
 * result is a fabric multiplied to black, with no warning from GL, three, or TypeScript.
 */

export interface MaterialLibrary {
  /** Painted-steel chassis body. Metal, moderately rough, spatially varied. */
  body: MeshStandardMaterial;
  /** Brushed anodised faceplate — the only anisotropic surface in the scene. */
  bezel: MeshPhysicalMaterial;
  /** Port cavities, vent slots, connector shrouds: dark glass-filled plastic. */
  dark: MeshStandardMaterial;
  /** Rack ears / rails: lighter anodised aluminium, distinct from the body so edges read. */
  rail: MeshStandardMaterial;
  /** Status LEDs. Emissive is driven by the instance colour; intensity crosses the bloom threshold. */
  led: MeshStandardMaterial;
  /** The uncollected-device shell: translucent, wireframed separately, never absent. */
  ghost: MeshStandardMaterial;
  /** 45-degree hatch applied to the top face of an uncollected chassis. */
  hatch: MeshBasicMaterial;
  /** Tier deck: a real slab, so a chassis has something to sit on and cast onto. */
  deck: MeshPhysicalMaterial;
  /** The floor under the lowest tier. */
  ground: MeshPhysicalMaterial;
  /** Contact-shadow decal — grounds a chassis even when the shadow map is off. */
  contact: MeshBasicMaterial;
  /** Selection halo disc on the tier plane beneath the selected chassis. */
  halo: MeshBasicMaterial;
  /** Hover shell: a thin back-face rim that is instant and costs one draw call. */
  hoverShell: MeshBasicMaterial;
  /** Operational-state rim around the chassis edge, colour per instance. */
  stateRim: MeshStandardMaterial;
  all(): Material[];
  dispose(): void;
}

export interface MaterialLibraryOptions {
  tokens: TokenPalette;
  maps: ProceduralMaps;
  /**
   * Emissive intensity for the status LED, in linear radiance.
   *
   * The bloom thresholds LUMINANCE, not the largest channel, and that is the whole reason this
   * number is what it is. `luminanceThreshold: 1.0` (postfx.ts) is the product's statement that a
   * glow means "this element is emitting" — but a saturated red carries only 0.2126 of its red
   * channel into luminance, so the CRITICAL band's LED was the one emitter the threshold could not
   * see. MEASURED at 2.2: `--band-critical` (#ff6b6b) reaches the bloom as
   * linear(1.0, 0.148, 0.148) x 1.4 (`bandEmissive`) x 2.2 = luminance 1.01 — level with the
   * threshold, smoothing 0.03 either side of it, so the worst band on the fabric glowed least.
   * Green (`--band-excellent`) cleared it and red did not, which would have made "is it emitting?"
   * a question about hue.
   *
   * 4.6 puts the DIMMEST band a factor of two clear of the threshold (critical -> luminance 2.12)
   * while the brightest stays inside AgX's shoulder, so every band reads as emitting and the hue
   * still survives the tone curve. Raise the emitter, never lower the threshold: lowering it would
   * let a bright painted lid glow, which is the claim this application must not make.
   */
  emissiveIntensity?: number;
}

/**
 * The chassis SILHOUETTE EDGE: a thin grazing-angle term that pulls the body's outgoing light toward
 * the theme's ink, so a chassis separates from the stage by an edge and not only by the top/front
 * luminance ratio.
 *
 * MEASURED (independent audit C5, 2026-09-22): chassis read as matte painted boxes with no rim or
 * edge highlight; the only form separation was top/front 126.8/93.3 = 1.36 at a grazing angle. The
 * term is Schlick-shaped (pow 5 of 1 - N·V), so it lives only on the bevel and the faces seen
 * edge-on, and it is a mix toward a colour rather than an addition of light — a lighten on the dark
 * stage (ink is pale) and a darken on the light one (ink is dark), i.e. the same contrast direction
 * as every other body step in `retintMaterials`. It is NOT emissive, so bloom never reads it as
 * "this element is emitting". The mix is capped at `SILHOUETTE_EDGE_MIX`, so a face is never
 * repainted; the band colour stays the band colour.
 */
export const SILHOUETTE_EDGE_MIX = 0.32;
const bodyEdge = { value: new Color(0.5, 0.5, 0.5) };
function withSilhouetteEdge(material: MeshStandardMaterial, colour: { value: Color }): void {
  const prev = material.onBeforeCompile;
  const prevKey = material.customProgramCacheKey.bind(material);
  material.onBeforeCompile = (shader, renderer) => {
    prev.call(material, shader, renderer);
    shader.uniforms.uSilhouetteEdge = colour;
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform vec3 uSilhouetteEdge;")
      .replace(
        "#include <opaque_fragment>",
        "{\n" +
          "  vec3 _vdir = isOrthographic ? vec3( 0.0, 0.0, 1.0 ) : normalize( vViewPosition );\n" +
          "  float _g = 1.0 - clamp( dot( normalize( normal ), _vdir ), 0.0, 1.0 );\n" +
          `  outgoingLight = mix( outgoingLight, uSilhouetteEdge, ${SILHOUETTE_EDGE_MIX.toFixed(3)} * _g * _g * _g * _g * _g );\n` +
          "}\n#include <opaque_fragment>",
      );
  };
  material.customProgramCacheKey = () => `${prevKey()}:silhouette-edge`;
}

export function buildMaterials(opts: MaterialLibraryOptions): MaterialLibrary {
  const { tokens, maps } = opts;
  const emissiveIntensity = opts.emissiveIntensity ?? 4.6;
  const stage = tokens.color("--stage-bg");
  const scratch = new Color();

  const body = withEmphasis(
    new MeshStandardMaterial({
      name: "chassis-body",
      // Stepped off the stage toward the ink so the silhouette reads against its own ground
      // without needing an outline to find it.
      color: mixTokens(stage, tokens.color("--text"), 0.3, new Color()),
      // DIELECTRIC, deviating from design-brief.md §4.6's `metalness 1.0` for the chassis body,
      // and physically so: a painted chassis is bare steel under an opaque dielectric coat, and
      // what the camera sees is the paint. At metalness 1 there is no diffuse term at all, so the
      // body is lit purely by environment reflection — measured in the browser, that rendered the
      // whole fabric as near-black silhouettes. The brief's binary-metalness rule is kept; only
      // the branch changes. The bezel and rack ears stay metal, because they are bare anodised
      // aluminium and genuinely have no diffuse term.
      metalness: 0,
      roughness: 0.52,
      roughnessMap: maps.chassisOrm,
      metalnessMap: maps.chassisOrm,
      aoMap: maps.chassisOrm,
      aoMapIntensity: 0.9,
      normalMap: maps.chassisNormal,
      envMapIntensity: 1,
    }),
  );
  body.normalScale.set(0.42, 0.42);
  withSilhouetteEdge(body, bodyEdge);

  const bezel = new MeshPhysicalMaterial({
    name: "chassis-bezel",
    color: mixTokens(stage, tokens.color("--text"), 0.4, new Color()),
    metalness: 1,
    roughness: 0.33,
    roughnessMap: maps.bezelOrm,
    // The port grille, on UV channel 1. Every non-grille bezel part samples its white metal texel
    // at a constant UV (chassis.ts GRILLE_METAL_UV), so this multiplies the frame by exactly 1.
    map: maps.grille,
    normalMap: maps.chassisNormal,
    anisotropy: 0.6,
    anisotropyRotation: 0,
    clearcoat: 0,
    envMapIntensity: 1.1,
  });
  bezel.normalScale.set(0.22, 0.22);
  withEmphasis(bezel);
  withGrilleNyquistFade(bezel);

  const dark = withEmphasis(
    new MeshStandardMaterial({
      name: "chassis-dark",
      // A measured physical albedo, not a UI colour, which is why it is a literal and not a token:
      // glass-filled black plastic sits near 3% reflectance in both themes, and a port cavity that
      // inverted with the theme would be a white hole in a dark chassis. Not pure black either —
      // §4.6 forbids it, a true black cavity destroys the tone mapper's shoulder, and it reads as a
      // hole punched through the geometry rather than as a recess.
      color: new Color().setRGB(0.014, 0.015, 0.019, LinearSRGBColorSpace),
      metalness: 0,
      roughness: 0.62,
      roughnessMap: maps.chassisOrm,
      envMapIntensity: 0.55,
    }),
  );

  const rail = withEmphasis(
    new MeshStandardMaterial({
      name: "chassis-rail",
      color: mixTokens(stage, tokens.color("--text"), 0.5, new Color()),
      metalness: 1,
      roughness: 0.3,
      roughnessMap: maps.bezelOrm,
      envMapIntensity: 1.05,
    }),
  );

  const led = withEmphasis(
    new MeshStandardMaterial({
      name: "status-led",
      color: scratch.setRGB(0.02, 0.02, 0.025, LinearSRGBColorSpace).clone(),
      metalness: 0,
      roughness: 0.55,
      emissive: new Color(1, 1, 1),
      emissiveIntensity,
      toneMapped: true,
    }),
    { emissiveFromInstanceColor: true },
  );

  const ghost = withEmphasis(
    new MeshStandardMaterial({
      name: "uncollected-ghost",
      color: mixTokens(stage, tokens.color("--claim-indeterminate"), 0.45, new Color()),
      metalness: 0,
      roughness: 0.78,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      envMapIntensity: 0.6,
    }),
  );

  const hatchMat = new MeshBasicMaterial({
    name: "uncollected-hatch",
    color: tokens.color("--claim-indeterminate"),
    alphaMap: maps.hatch,
    transparent: true,
    opacity: 0.85,
    depthWrite: false,
  });

  /* ── depthWrite: false on the two faded ground planes ───────────────────────────────────────
   *
   * This is not a tuning preference, it is the fix for two visible defects that share one cause.
   *
   * A depth write is not alpha-weighted. These planes carry a radial alpha fade that reaches zero
   * well inside the quad, so the OUTER part of a deck paints nothing at all — and, with depthWrite
   * on, still stamped the depth buffer across its whole rectangle. Everything drawn afterwards and
   * behind it was then discarded by the depth test. Two consequences, both measured in the browser
   * at a low camera over the core tier (dark, tier high, real GPU):
   *
   *   1. The "hard rectangle" the decks were never supposed to terminate on (ground.ts's own
   *      comment promises a fade "rather than terminating on a hard rectangle"). What was visible
   *      was not painted deck — it was the rectangular silhouette of ERASED background. The fade
   *      was working perfectly; the depth write was drawing the rectangle.
   *
   *   2. Every cable behind a deck vanished completely instead of showing through an 85 %-opacity
   *      surface. With the fabric framed on core1, the nine core-to-access cables simply stopped
   *      at a straight line partway down the frame. Hiding the alternate path is precisely the
   *      failure design-brief.md §4.5 forbids, and it was being done by the floor.
   *
   * Both disappear with the write off, and nothing needs it: the chassis are OPAQUE, so they are
   * drawn before any transparent surface and still occlude these planes through the depth TEST,
   * which stays on. The decks only ever needed to be hidden BY solid things, never to hide things
   * themselves. Verified by A/B at runtime — toggling mipmaps on the fade texture, the other
   * candidate, changed nothing at all. */
  const deck = new MeshPhysicalMaterial({
    name: "tier-deck",
    color: mixTokens(stage, tokens.color("--text"), 0.045, new Color()),
    metalness: 0,
    roughness: 0.88,
    roughnessMap: maps.groundOrm,
    aoMap: maps.groundOrm,
    aoMapIntensity: 0.85,
    alphaMap: maps.radialFade,
    transparent: true,
    depthWrite: false,
    opacity: 0.85,
    envMapIntensity: 0.75,
  });
  /* GRAZING FADE (C5 critic, 2026-09-22). Near the polar clamp (78 degrees) a faded deck or node
     pad is foreshortened ~5:1, and its radial fade plus the Fresnel rise of its environment term
     turned each pad — 8 chassis half-widths across — into a horizontal light smear reaching well
     past the chassis footprint. The surface's job is grounding, and seen edge-on it has almost no
     projected area to ground anything with, so it steps back as the view grazes: full presence at
     the working views (|n.v| >= 0.55, i.e. polar <= ~57 degrees), about an eighth at the clamp.
     MEASURED: at a third the smear was still there (std unchanged); with the surfaces removed
     entirely it vanished, which is what identified the deck/pad as its source.
     A property of the SURFACE, so decks and pads — which share this material — get it together. */
  deck.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <opaque_fragment>",
      `diffuseColor.a *= mix( ${DECK_GRAZE_FLOOR.toFixed(3)}, 1.0, smoothstep( 0.22, 0.55, abs( dot( normalize( normal ), normalize( vViewPosition ) ) ) ) );
#include <opaque_fragment>`,
    );
  };
  deck.customProgramCacheKey = () => "atlas-deck-graze";

  const ground = new MeshPhysicalMaterial({
    name: "ground",
    color: mixTokens(stage, new Color(0, 0, 0), 0.18, new Color()),
    metalness: 0,
    roughness: 0.86,
    roughnessMap: maps.groundOrm,
    aoMap: maps.groundOrm,
    aoMapIntensity: 1,
    alphaMap: maps.radialFade,
    transparent: true,
    // Same reason as the deck above: a faded plane that writes depth erases what is behind the
    // part of it that paints nothing. The floor is the larger of the two offenders by area.
    depthWrite: false,
    opacity: 1,
    envMapIntensity: 0.6,
  });

  /* NormalBlending with a black diffuse IS a multiply: the fragment resolves to
     dst * (1 - alpha), which is exactly what a shadow does to whatever it lands on. The alpha
     profile is therefore the whole design, and it lives in `maps.contactFade` — a plateau, not a
     radial peak, because the peak of a radial fade is the part a chassis stands on top of. */
  const contact = new MeshBasicMaterial({
    name: "contact-shadow",
    color: new Color(0, 0, 0),
    alphaMap: maps.contactFade,
    transparent: true,
    opacity: 0.52,
    depthWrite: false,
  });

  const halo = new MeshBasicMaterial({
    name: "selection-halo",
    color: tokens.color("--accent"),
    alphaMap: maps.radialFade,
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });

  const hoverShell = new MeshBasicMaterial({
    name: "hover-shell",
    color: tokens.color("--text"),
    transparent: true,
    opacity: 0,
    depthWrite: false,
    // An inverted hull: only the part of the shell that escapes the chassis is drawn, which is what
    // turns a uniformly scaled copy into a rim of roughly even apparent thickness.
    side: BackSide,
  });

  const stateRim = withEmphasis(
    new MeshStandardMaterial({
      name: "state-rim",
      // Near-black diffuse on purpose: the ring is read by its EMISSION, which the instance colour
      // drives. A white diffuse would put a bright unlit ring on every deck whenever the light
      // happens to graze it, and would fail the dielectric-albedo band besides.
      color: new Color().setRGB(0.05, 0.05, 0.06, LinearSRGBColorSpace),
      metalness: 0,
      roughness: 0.5,
      emissive: new Color(1, 1, 1),
      emissiveIntensity: 0.55,
    }),
    { emissiveFromInstanceColor: true },
  );

  const lib: MaterialLibrary = {
    body,
    bezel,
    dark,
    rail,
    led,
    ghost,
    hatch: hatchMat,
    deck,
    ground,
    contact,
    halo,
    hoverShell,
    stateRim,
    all(): Material[] {
      return [body, bezel, dark, rail, led, ghost, hatchMat, deck, ground, contact, halo, hoverShell, stateRim];
    },
    dispose(): void {
      for (const m of lib.all()) m.dispose();
    },
  };
  return lib;
}

/**
 * Re-tint an existing library from a new palette. Used on theme change: rebuilding every material
 * would recompile every shader and drop a visible number of frames, and the geometry has not moved.
 */
/*
 * How far the light-theme chassis BODY steps from the stage toward the ink.
 *
 * Was 0.8, which killed the band channel in light theme: the body's band tint arrives as a
 * MULTIPLY on the albedo, and at 0.8 the albedo was ~0.18 linear, so the diffuse term that carries
 * the tint was small next to the untinted environment specular on the lid. Measured (real GPU,
 * light, DPR 2, review audit `_ra_theme`): core1 (Critical) top face 167,163,167 and core2 (Good)
 * 148,152,152 — both neutral grey, while FabricLegend still promised "chassis colour — health
 * band". The body now sits at mid-grey, where the diffuse term dominates and the band hue survives,
 * and the chassis still separates from the near-white stage by a wide luminance margin. The
 * measured before/after lives with the render-audit notes in scene.ts (`BODY_BAND_TINT`).
 */
export const LIGHT_BODY_STEP = 0.55;

/*
 * Dark-theme deck/pad lift and opacity. Was 0.06 at 0.85: lit by the key and the environment, that
 * deck rendered 3-10x the stage's luminance directly under each chassis (render audit: podacc2 69
 * vs stage 14, access11 47 vs 12), so hardware sat on a pale glow — a spotlight, not a surface —
 * and the contact decal was darkening a halo rather than grounding anything.
 */
export const DARK_DECK_STEP = 0.01;
export const DARK_DECK_OPACITY = 0.6;
export const DARK_GROUND_ENV = 0.15;
/*
 * The dark-theme glow's real source. Ablation (dark, real GPU): darkening the deck and floor
 * ALBEDO to the stage colour and cutting their environment reflection changed nothing visible;
 * hiding the floor removed the broad pool and hiding the decks/pads removed the halos. What is left
 * when albedo is near zero is the KEY light's GGX lobe: at this camera's grazing angle Fresnel lifts
 * a rough dielectric's direct specular far above its diffuse term, painting a pale sheen under
 * every node. The ground planes are therefore MeshPhysicalMaterial so their specular can be scaled.
 */
export const DARK_GROUND_SPECULAR = 0.15;
/*
 * Light-theme contact decal. Was 0.42: measured under a focused chassis (light, real GPU) the decal
 * darkened its surround by only ~11 of 255 levels (226 against a 237 pad), so nothing read as
 * resting ON the surface. 0.6 is where the base darkening is visible without reading as a hole.
 */
export const LIGHT_CONTACT_OPACITY = 0.6;
/*
 * Light-theme uncollected-chassis ("ghost") shell. Was tint 0.72 at opacity 0.4: measured (real GPU,
 * light, high, 1920x1080) the fill of the three never-collected chassis rendered 1.82-2.08:1 against
 * the ground 8 px outside them — the legend's "collection: topology only" state, drawn under the
 * 3:1 bar a state indicator needs (acceptance D4). The outline and the "?" label carried it; the
 * fill did not. The shell stays translucent (cables behind it still read through it) but is now
 * dense and hue-saturated enough to be an indicator on its own. Re-measure with the fill probe
 * whenever this moves: it is a contrast claim, not a taste.
 */
export const LIGHT_GHOST_DEEPEN = 0.4;
export const LIGHT_GHOST_OPACITY = 0.92;
/** Light-theme floor opacity; see `retintMaterials`. */
export const LIGHT_FLOOR_OPACITY = 0.2;

export function retintMaterials(lib: MaterialLibrary, tokens: TokenPalette): void {
  const stage = tokens.color("--stage-bg");
  const light = tokens.theme === "light";
  /*
   * Hardware steps FURTHER from the stage on light than on dark, and that asymmetry is the point.
   * On a near-black stage a 30 % step toward the ink is already a clear separation; on a near-white
   * one the same step leaves a pale chassis on a pale ground with almost no silhouette. Measured in
   * the browser: at the symmetric value the light theme's fabric was barely distinguishable from
   * its backdrop. The light theme is not the dark theme inverted (acceptance C4), and this is one
   * of the places where treating it as one produces a visibly worse result.
   */
  mixTokens(stage, tokens.color("--text"), light ? LIGHT_BODY_STEP : 0.3, lib.body.color);
  /* The silhouette edge's target: most of the way to the ink, in the linear buffer the body is lit
     in. See withSilhouetteEdge. */
  mixTokens(stage, tokens.color("--text"), light ? 0.95 : 0.85, bodyEdge.value);
  mixTokens(stage, tokens.color("--text"), light ? 0.86 : 0.4, lib.bezel.color);
  mixTokens(stage, tokens.color("--text"), light ? 0.7 : 0.5, lib.rail.color);
  if (light) {
    // The indeterminate hue, deepened toward the ink so the lit, translucent shell still lands
    // under the ground by 3:1. See LIGHT_GHOST_DEEPEN.
    mixTokens(tokens.color("--claim-indeterminate"), tokens.color("--text"), LIGHT_GHOST_DEEPEN, lib.ghost.color);
  } else {
    mixTokens(stage, tokens.color("--claim-indeterminate"), 0.45, lib.ghost.color);
  }
  // A ghost on a near-white stage at 22 % is invisible, and an invisible "we never reached this
  // device" is the absence-as-health failure in its purest form. The light theme therefore both
  // pushes the tint further toward the indeterminate hue and raises the opacity.
  lib.ghost.opacity = light ? LIGHT_GHOST_OPACITY : 0.22;
  // On light the shell is itself the indeterminate hue now, so the hatch deepens further toward
  // the ink: the same pattern, still legible on the shell, and it adds to the fill's contrast
  // rather than lifting it (a pale hatch measured the fill back down to 2.4-2.8:1).
  if (light) mixTokens(tokens.color("--claim-indeterminate"), tokens.color("--text"), 0.65, lib.hatch.color);
  else lib.hatch.color.copy(tokens.color("--claim-indeterminate"));
  // The deck steps AWAY from the stage in whichever direction the theme leaves room: a step toward
  // the ink is a lift on a near-black stage and a darkening on a near-white one. A fixed step would
  // be invisible in one theme and, on light, would push a dielectric past the albedo ceiling.
  const deckStep = tokens.theme === "dark" ? DARK_DECK_STEP : 0.2;
  mixTokens(stage, tokens.color("--text"), deckStep, lib.deck.color);
  lib.deck.opacity = light ? 0.85 : DARK_DECK_OPACITY;
  /* The floor. On dark it is darkened toward black as before. On light it is NOT darkened and is
     faded right back: lit at any albedo a dielectric can have, a floor on the light stage renders
     BELOW the page's near-white backdrop, and its radial alpha fade then paints a dark disc under
     the empty middle of the fabric — a shadow with nothing casting it (render audit, light, both
     tiers identical: luma 238 at the frame edge falling to 191 under the fabric's centre). */
  // 0.12 on light, not 0: the stage itself (0.944 sRGB) is over the dielectric albedo ceiling (0.9).
  mixTokens(stage, new Color(0, 0, 0), light ? 0.12 : 0.18, lib.ground.color);
  lib.ground.opacity = light ? LIGHT_FLOOR_OPACITY : 1;
  /* Environment specular on the two ground planes. On dark it was the glow: a dielectric's
     environment reflection is ADDITIVE and independent of albedo, and at this camera's grazing
     angle Fresnel lifts it well past the diffuse term, so darkening the deck albedo alone changed
     almost nothing (ablation, dark, real GPU: hiding floor, decks and pads one at a time left a
     pale haze under every node until the reflection itself was cut). */
  lib.deck.envMapIntensity = light ? 0.75 : DARK_GROUND_ENV;
  lib.ground.envMapIntensity = light ? 0.6 : DARK_GROUND_ENV;
  lib.deck.specularIntensity = light ? 1 : DARK_GROUND_SPECULAR;
  lib.ground.specularIntensity = light ? 1 : DARK_GROUND_SPECULAR;
  lib.halo.color.copy(tokens.color("--accent"));
  lib.hoverShell.color.copy(tokens.color("--text"));
  // Light theme: a black contact decal on a near-white ground is too heavy; a dark grey at lower
  // opacity is what a real soft shadow looks like on a pale floor.
  lib.contact.color.setRGB(light ? 0.06 : 0, light ? 0.07 : 0, light ? 0.09 : 0);
  /* RAISED 0.52 -> 0.7 (dark) and 0.3 -> 0.42 (light), 2026-09-21, measured not guessed.
     With the plateau falloff in place, a horizontal luminance scan across the deck either side of
     a focused chassis (real GPU, tier high, dark) reads, from no decal at all:
       no decal  ... 99 98 [chassis] 96 94 ...
       0.52      ... 98 93 [chassis] 80 73 ...
       0.70      ... 98 91 [chassis] 73 63 ...
       0.85      ... 98 89 [chassis] 67 53 ...
     0.52 is a ~20 % trough on a deck that is already near black; 0.85 starts reading as a painted
     black pool rather than as contact. 0.70 is the value where the chassis stops floating and the
     deck is still a deck. */
  lib.contact.opacity = light ? LIGHT_CONTACT_OPACITY : 0.7;
  /*
   * The state ring changes MECHANISM between themes, not just value.
   *
   * On dark it is read as an emitter: a near-black albedo with the instance colour driving
   * emissive radiance, which is what makes it legible against a near-black deck. On light an
   * emitter washes out — a bright ring on a bright ground has nowhere to go — so the ring becomes
   * a lit surface instead: a pale albedo the instance colour tints, with emission cut to a trace.
   * Same geometry, same three shapes, opposite optics.
   */
  lib.stateRim.color.setRGB(
    light ? 0.62 : 0.05,
    light ? 0.62 : 0.05,
    light ? 0.64 : 0.06,
    LinearSRGBColorSpace,
  );
  lib.stateRim.emissiveIntensity = light ? 0.16 : 0.55;
  const [tr, tg, tb] = agxInverse([stage.r, stage.g, stage.b]);
  recedeTarget.value.setRGB(tr, tg, tb, LinearSRGBColorSpace);
  recedeMix.value = RECEDE_MIX[light ? "light" : "dark"];
  for (const m of lib.all()) m.needsUpdate = true;
}

/** Textures are shared across materials, so disposal is centralised rather than per material. */
export function disposeTextures(textures: Iterable<Texture | null | undefined>): void {
  for (const t of textures) {
    if (t !== null && t !== undefined) t.dispose();
  }
}
