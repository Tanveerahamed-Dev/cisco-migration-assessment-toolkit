/**
 * cables.ts — links as cables: real width, real curvature, real encoding.
 *
 * `LineBasicMaterial` is forbidden here and the reason is worth stating once, because it is the
 * single most common way a three.js network view ends up looking cheap: WebGL silently ignores
 * `linewidth > 1` on essentially every platform. It does not warn, it does not throw, it renders a
 * one-pixel hairline forever, and no post-processing pass can rescue it. Every visible link in this
 * scene is therefore a `LineSegments2` with a `LineMaterial`, which expands each segment into
 * camera-facing quads in the vertex shader and gives genuine, anti-aliased width.
 *
 * What a cable encodes, and the rule that governs it: FOUR independent channels, none of which is
 * colour alone.
 *
 *   width   → observed link speed, with a distinct THINNEST step for "speed not observed"
 *   dash    → operational state: solid = up, long-dash = down, dotted = unknown
 *   colour  → the loudest fact about the link (down, bridge, unmeasured, ordinary)
 *   strands → a port-channel is drawn as a bundle; a graph bridge is drawn doubled
 *
 * `null` never becomes a healthy default. A link whose centrality was never computed — 19 of the
 * 44 in this snapshot — is drawn in `--claim-indeterminate` with a long, tick-broken dash and reports
 * `notObserved: ["centrality"]`, because "we did not measure whether cutting this partitions the
 * graph" and "cutting this is safe" are opposite claims.
 */
import {
  Color,
  DynamicDrawUsage,
  InstancedBufferAttribute,
  InstancedInterleavedBuffer,
  InterleavedBufferAttribute,
  Vector3,
} from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import type { Link } from "../../core/types";
import { RECEDE_ATTRIBUTE, type TokenPalette } from "../materials";
import { RECEDE_DEPTH } from "../emphasis";
import { agxForward, agxInverse, floorLuminance, stageGround, toLuminance } from "../env";
import type { Vec3 } from "../layout";

/* ── cable ink: the contrast floor, as a property of the colour pipeline ─────────────────────────
 *
 * MEASURED (independent audit, D4): with a finding selected, off-subject cables reached the screen
 * at 1.09-1.49:1 on the light stage and 1.92-2.67:1 on the dark one, against a WCAG 1.4.11 floor of
 * 3:1 — while every token they were painted in passes on paper. Two things in the pipeline, not the
 * tokens, did that:
 *
 *   1. The token was written into the composer's LINEAR HDR buffer as-is and then went through AgX
 *      with everything else, so what landed was AgX(token), not the token.
 *   2. Recession thinned ALPHA. The backdrop's pre-image on the light stage is ~4-6 linear (see
 *      env.ts createBackdrop), so blending even a third of it into a cable before the tone map
 *      washes the cable into the ground. On the dark stage it multiplied radiance toward black.
 *
 * So the ink is now DISPLAY-referred, like the backdrop: the colour a cable should land on is
 * decided in display space, held to a contrast floor against the worst-case ground the backdrop
 * gradient can put behind it, and only then converted to the AgX pre-image that is written into
 * the buffer. Recession is a colour, not an alpha: a second, precomputed display colour — the ink
 * desaturated and pulled toward the ground until it sits exactly on its own (lower) floor. Both are
 * guarded for EVERY token, so no future token choice can reintroduce the failure.
 */
/** Full-presence display contrast against the worst ground. 3:1 is the WCAG floor; the margin is
 *  for SMAA, which on a 1-2 px stroke pulls the strongest pixel ~20-25 % toward the ground
 *  (MEASURED, review/_r3d_cc.mjs: a receded dot designed at 3.8:1 landed at 2.9-3.0:1). */
export const CABLE_INK_FLOOR = 4.6;
/** A fully receded cable lands here: still legible context, quieter than the subject (which also
 *  keeps its chroma). The brief quotes 3.36:1 for a dimmed off-path link; that figure is the INK,
 *  and SMAA's measured loss on thin strokes is why the ink sits above it. */
export const CABLE_RECEDED_FLOOR = 4.0;
/** How much hue a receded cable keeps. Matches the chassis, which desaturate as they recede. */
const RECEDED_CHROMA = 0.35;
/** Instance attribute carrying each segment's receded ink (AgX pre-image, linear). */
export const RECEDE_INK_ATTRIBUTE = "aRecedeInk";

const luminance = (c: Vec3): number => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];

/** WCAG contrast of two relative luminances (linear-light, 0..1). */
export function contrastOfLuminance(a: number, b: number): number {
  const hi = Math.max(a, b);
  const lo = Math.min(a, b);
  return (hi + 0.05) / (lo + 0.05);
}

/** The ground a cable has to hold its contrast against, and which way the ink must go to do it.
 *  The stage's own ground (env.ts `stageGround`), shared with the receded-chassis floor. */
export function cableGround(tokens: TokenPalette): { y: number; inkDarker: boolean } {
  return stageGround(tokens);
}

export interface CableInk {
  /** Display colours (linear sRGB, what the screen should show). */
  display: { ink: Vec3; receded: Vec3 };
  /** The same two colours as AgX pre-images — what is written into the HDR buffer. */
  ink: Color;
  receded: Color;
}

/**
 * Resolve one colour token into the pair of cable inks. Pure given the palette; memoised per
 * palette by the caller. Total over every token: a token that already clears the floor is left
 * exactly as designed, one that does not is moved along its own luminance axis until it does.
 */
export function cableInk(tokens: TokenPalette, token: string, restChroma = 1): CableInk {
  const { y: groundY, inkDarker } = cableGround(tokens);
  const raw = tokens.color(token);
  let ink: Vec3 = [raw.r, raw.g, raw.b];
  if (restChroma < 1) {
    // Chroma pulled toward the ink's own luminance BEFORE the floor is applied, so the contrast
    // floor is held by the colour actually drawn, not by the token it was derived from.
    const y0 = luminance(ink);
    ink = [y0 + (ink[0] - y0) * restChroma, y0 + (ink[1] - y0) * restChroma, y0 + (ink[2] - y0) * restChroma];
  }
  const inkFloorY = floorLuminance(groundY, CABLE_INK_FLOOR, inkDarker);
  const passes = inkDarker ? luminance(ink) <= inkFloorY : luminance(ink) >= inkFloorY;
  if (!passes) ink = toLuminance(ink, inkFloorY);

  const iy = luminance(ink);
  const desat: Vec3 = [
    iy + (ink[0] - iy) * RECEDED_CHROMA,
    iy + (ink[1] - iy) * RECEDED_CHROMA,
    iy + (ink[2] - iy) * RECEDED_CHROMA,
  ];
  const recededY = floorLuminance(groundY, CABLE_RECEDED_FLOOR, inkDarker);
  // Never let "receded" be LOUDER than present: an ink that only just clears its own floor keeps
  // its luminance and recedes by chroma alone.
  const closer = inkDarker ? Math.max(recededY, iy) : Math.min(recededY, iy);
  const receded = toLuminance(desat, closer);

  const pre = (c: Vec3): Color => {
    const [r, g, b] = agxInverse(c);
    return new Color(r, g, b);
  };
  return { display: { ink, receded }, ink: pre(ink), receded: pre(receded) };
}

/**
 * Every colour token `classifyLink` can paint a cable in — discovered by running it over every
 * status x bridge x speed combination, not listed by hand, so a new encoding joins the fit below
 * the day it is written.
 */
export function cableColourTokens(): string[] {
  const out = new Set<string>();
  for (const opStatus of ["up", "down", "unknown", "admin-down", null]) {
    for (const isBridge of [true, false, null]) {
      for (const speedMbps of [null, 100, 1000, 10000]) {
        const link = { id: "L", a: "a", b: "b", speedMbps, opStatus, isBridge, isPortChannel: false, members: [] };
        out.add(classifyLink(link as unknown as Link).colorToken);
      }
    }
  }
  return [...out].sort();
}

/**
 * The exponent a cable's edge coverage is raised to before it becomes alpha, so that what reaches
 * the SCREEN is linear in coverage (C5, "1px hairline links").
 *
 * WHY. The coverage blend happens in the composer's linear HDR buffer, before AgX. On the light
 * stage the ground's pre-image is ~3.6 and a dark ink's ~0.03, so a 50 %-covered edge pixel holds
 * ~1.8 linear — and AgX, which compresses the top of its range, puts that on screen only 16-18 % of
 * the way from the ground to the ink. The anti-aliased fringe vanished and light-theme cables
 * MEASURED ~1 CSS px (median coverage-integrated width 1.83 px, a one-pixel core on 32 of 72
 * crossings, against 2.76 px and 2 of 51 on the dark stage). On the dark stage the same blend lands
 * 63-83 % of the way, so dark strokes read fatter than their encoded width.
 *
 * HOW. For this palette's worst-case ground (`cableGround`) and every ink AND receded ink a cable
 * can carry, the displayed position of a pixel blended at alpha c^gamma is computed through the
 * real AgX forward curve, and gamma is chosen (0.01 steps) to minimise the squared distance from
 * the geometric coverage c over c = 0.1..0.9. One exponent per palette: the inks of one stage sit
 * close together in luminance, and a per-fragment inverse tone map would cost a lookup per pixel for
 * a residual the unit test bounds at +-0.15 at half coverage.
 */
const gammaCache = new WeakMap<TokenPalette, number>();
export function coverageGamma(tokens: TokenPalette): number {
  const hit = gammaCache.get(tokens);
  if (hit !== undefined) return hit;
  const { y: groundY } = cableGround(tokens);
  const gL = agxInverse([groundY, groundY, groundY]);
  const inks: { pre: Vec3; shown: number }[] = [];
  for (const token of cableColourTokens()) {
    const pair = cableInk(tokens, token);
    for (const c of [pair.ink, pair.receded]) {
      const pre: Vec3 = [c.r, c.g, c.b];
      inks.push({ pre, shown: luminance(agxForward(pre)) });
    }
  }
  const errorAt = (g: number): number => {
    let err = 0;
    for (const ink of inks) {
      if (Math.abs(groundY - ink.shown) < 1e-6) continue;
      for (let c = 0.1; c < 0.95; c += 0.1) {
        const a = Math.pow(c, g);
        const blended: Vec3 = [
          gL[0] + (ink.pre[0] - gL[0]) * a,
          gL[1] + (ink.pre[1] - gL[1]) * a,
          gL[2] + (ink.pre[2] - gL[2]) * a,
        ];
        const shown = (groundY - luminance(agxForward(blended))) / (groundY - ink.shown);
        err += (shown - c) ** 2;
      }
    }
    return err;
  };
  /* Coarse (0.1) then fine (0.01) around the coarse minimum: ~50 evaluations instead of ~280, because
     this runs inside buildCables on the scene-creation task (acceptance E5 budgets that task). */
  let best = 1;
  let bestErr = Infinity;
  for (let g = 0.2; g <= 3.0 + 1e-9; g += 0.1) {
    const e = errorAt(g);
    if (e < bestErr) [best, bestErr] = [g, e];
  }
  const centre = best;
  for (let g = centre - 0.1; g <= centre + 0.1 + 1e-9; g += 0.01) {
    const e = errorAt(g);
    if (g > 0 && e < bestErr) [best, bestErr] = [g, e];
  }
  best = Math.round(best * 100) / 100;
  gammaCache.set(tokens, best);
  return best;
}

/** Set the display-linear coverage exponent on a material made by createCableMaterial. */
export function setCoverageGamma(mat: LineMaterial, gamma: number): void {
  const u = mat.uniforms.coverageGamma;
  if (u === undefined) mat.uniforms.coverageGamma = { value: gamma };
  else u.value = gamma;
}

/** What AgX will actually put on screen for a pre-image — exported for the contrast ratchet. */
export function displayedLuminance(pre: Color): number {
  return luminance(agxForward([pre.r, pre.g, pre.b]));
}

/** Memoised `cableInk` for one palette; a new palette (theme change) gets a new table. */
function inkTable(tokens: TokenPalette): (token: string, restChroma?: number) => CableInk {
  const cache = new Map<string, CableInk>();
  return (token, restChroma = 1) => {
    const key = `${token}|${restChroma}`;
    let hit = cache.get(key);
    if (hit === undefined) {
      hit = cableInk(tokens, token, restChroma);
      cache.set(key, hit);
    }
    return hit;
  };
}

/**
 * Chroma a cable keeps AT REST, by what its colour encodes.
 *
 * design-brief.md §1: "Chroma is spent on severity and operational state only." A bridge is a
 * topology ROLE. At full chroma `--link-bridge` was the most saturated hue in every overview frame
 * — 17 magenta access uplinks outshouting the Critical band channel (C5 critic, 2026-09-22). The
 * role is still carried by its own hue AND by the doubled rails (a shape channel, so never colour
 * alone); it simply stops being the loudest thing on the stage. Keyed on the visual's encoding
 * (`LinkVisual.roleOnly`), not on a token name at the call site.
 */
export const ROLE_REST_CHROMA = 0.5;
function restChromaOf(visual: LinkVisual): number {
  return visual.roleOnly ? ROLE_REST_CHROMA : 1;
}

/**
 * Screen-space gap between a cable's parallel rails, in CSS pixels.
 *
 * Rails used to be separate polylines offset in WORLD units (bridge +-0.45, port-channel strands
 * 0.62 apart). At the overview a unit projects to well under a pixel, so the two 2.7 px strokes
 * overlapped and their AA ramps beat against each other into a dark stipple inside every bundle —
 * aliasing on the fabric's dominant long diagonals (C5 critic: holes of 2f1b30 / 0c0f16 between
 * magenta strand pixels at DPR 1, both tiers). A world-unit gap is only a gap at some dolly. So the
 * rails are now drawn by ONE stroke whose shader cuts gaps of a fixed pixel width across it: the
 * rails stay separate at every zoom and every DPR, and a bridge's gap stays visibly wider than a
 * port channel's, which is the shape channel the legend promises.
 */
export const BRIDGE_RAIL_GAP_PX = 3;
export const STRAND_RAIL_GAP_PX = 2;
export function railsOf(visual: LinkVisual): { rails: number; gapPx: number } {
  const rails = visual.strands * (visual.doubled ? 2 : 1);
  return { rails, gapPx: visual.doubled ? BRIDGE_RAIL_GAP_PX : STRAND_RAIL_GAP_PX };
}

export type DashStyle = "solid" | "dashed" | "dotted" | "short";

export interface LinkVisual {
  linkId: string;
  /** Line width in CSS pixels. `worldUnits` is false, so a link's weight does not change with dolly. */
  widthPx: number;
  /** A CSS custom property name — never a literal colour. */
  colorToken: string;
  dash: DashStyle;
  /** Parallel strands. > 1 only for a port channel: one cable drawn for a bundle is a lie. */
  strands: number;
  /** Drawn with a second rail: this link's removal partitions the graph. */
  doubled: boolean;
  /** The colour encodes a topology ROLE only (no severity, no state): quieter at rest. */
  roleOnly: boolean;
  /** Fields that were null or absent in the snapshot. Rendered as unmeasured, never as healthy. */
  notObserved: string[];
  /** One sentence a tooltip or legend can print verbatim. */
  reason: string;
  /**
   * What the DRAWN pattern asserts, one entry per channel that asserts something (the dash/colour
   * of a state, the short-dash centrality gap, the doubled bridge rail). Set in the same branch
   * that picks the pattern, so it cannot describe a different cable than the one drawn. Every
   * non-canvas surface that states a link's status in short form (the Fabric list row,
   * FabricA11yTree `linkCutMeta`) must carry each of these — see link-encoding.parity.test.tsx.
   * `key` is the phrase a row must contain; `words` is how to say it when the row does not yet;
   * `gap` marks an absence rather than an observation.
   */
  drawnClaims: DrawnClaim[];
}

export interface DrawnClaim {
  key: string;
  words: string;
  gap: boolean;
}

/**
 * The thinnest stroke any cable may draw, in CSS pixels (design-brief's 2 CSS px minimum stroke).
 *
 * The steps used to start at 1.5. MEASURED (independent audit C5, 2026-09-22, DSF 2): a grey
 * speed-not-observed link came out ~1.7 CSS px across its section, under the brief's floor, and at
 * close range cables read thinner than the ports they enter. The whole ladder is shifted up by the
 * same 0.5 px, so the four steps keep their exact 0.6 px spacing and the thinnest still means
 * "speed not observed"; only the floor moved.
 */
export const MIN_STROKE_PX = 2;
/** Width steps. The thinnest is reserved for "speed not observed" so absence has its own weight. */
const WIDTH_SPEED_UNOBSERVED = MIN_STROKE_PX;
const WIDTH_100M = 2.6;
const WIDTH_1G = 3.2;
const WIDTH_FAST = 3.8;

/**
 * Width of the analytic edge filter on a cable, in pixels — and, by the same number, how much
 * wider the drawn quad is than the width the encoding asks for.
 *
 * The two uses have to be one constant, because together they are what keeps the width CHANNEL
 * intact. The filter is linear and centred ON the nominal edge, so half of it falls inside the
 * stroke and half in the margin the quad was widened by; the ink that lands on screen is therefore
 * the nominal width, at every width. The four speed steps keep their exact relative weight
 * (2.0 : 2.6 : 3.2 : 3.8) and only the outer EXTENT grows, by the same amount on every cable —
 * a constant, not a distortion of the encoding.
 *
 * It was measured, not chosen. On review/_audit_cableaa.mjs at `high` (real GPU, dark), the share
 * of background-to-cable crossings that are zero-intermediate hard steps, and the single-pixel
 * holes punched into the strokes:
 *
 *   no term at all (shipped)   77.1 %   108 holes
 *   no term, tone split only   63.5 %   108 holes
 *   filter 1.0 px              69.7 %   105 holes
 *   filter 1.6 px              64.1 %    45 holes
 *   filter 2.2 px              57.7 %    17 holes
 *
 * 2.2 keeps winning on the metric and loses on the picture: at that width a 1.5 px cable never
 * reaches full coverage anywhere across its section, so the thinnest speed step — the one reserved
 * for "speed not observed" — starts reading as a smear instead of a wire. 1.6 is the last value
 * where every width still has an opaque core.
 *
 * The first attempt ramped INWARD from the quad edge without widening the quad, and that is the
 * mistake this constant's double duty exists to prevent: `cablePixels` fell from 2882 to 1195 and
 * the cables had quietly gone translucent while the aliasing metric looked like it had improved.
 *
 * In CSS pixels where it widens the quad (`LineMaterial.linewidth` is), in device pixels where it
 * filters (`fwidth` is). They coincide at DPR 1; at DPR 2 the residual is a fraction of a pixel.
 */
const CABLE_EDGE_AA_PX = 1.6;
/** Radiance at a stroke's edge relative to its crown — the cylindrical shading term. */
const CABLE_TUBE_EDGE = 0.68;
/**
 * Classify one link into its visual channels. Pure, total, and the natural unit test for the whole
 * encoding: the honesty rules are all expressible as assertions on the returned record.
 */
export function classifyLink(link: Link): LinkVisual {
  const notObserved: string[] = [];
  const drawnClaims: DrawnClaim[] = [];

  const speed = link.speedMbps;
  let widthPx: number;
  if (speed === null || speed <= 0) {
    // 0 Mbps reaches us from the collector for a port whose speed it could not read. Treating it
    // as "zero bandwidth" would invent a fact; it is an absence and is drawn as one.
    notObserved.push("speed");
    widthPx = WIDTH_SPEED_UNOBSERVED;
  } else if (speed <= 100) {
    widthPx = WIDTH_100M;
  } else if (speed <= 1000) {
    widthPx = WIDTH_1G;
  } else {
    widthPx = WIDTH_FAST;
  }

  const status = link.opStatus;
  let dash: DashStyle;
  let colorToken: string;
  let reason: string;

  if (status === "down") {
    dash = "dashed";
    colorToken = "--state-down";
    reason = "operational state: down";
    drawnClaims.push({ key: "state down", words: "state down", gap: false });
  } else if (status === "up") {
    dash = "solid";
    colorToken = "--claim-out-of-scope";
    reason = "operational state: up";
  } else {
    // Anything that is not literally up or down — including the string "unknown" this snapshot
    // uses — is a third thing. It is never quietly folded into "up".
    dash = "dotted";
    colorToken = "--state-unknown";
    notObserved.push("operational state");
    drawnClaims.push({ key: "state not observed", words: "state not observed", gap: true });
    reason = `operational state not observed (${status})`;
  }

  let doubled = false;
  if (link.isBridge === true) {
    doubled = true;
    // A topology ROLE, not a severity: its own token so a cut-edge never reads as a High finding.
    colorToken = "--link-bridge";
    reason = `${reason}; cutting this link partitions the graph`;
    // The rail is the SNAPSHOT's flag; the row attributes it rather than stating it as fact.
    drawnClaims.push({ key: "cut partitions", words: "snapshot: cut partitions", gap: false });
  } else if (link.isBridge === null) {
    notObserved.push("centrality");
    if (status === "up") {
      // Only claim the indeterminate channel when no louder observed fact is using it. A link that
      // is DOWN and also unmeasured is drawn down — the observed failure outranks the gap.
      dash = "short";
      colorToken = "--claim-indeterminate";
      drawnClaims.push({ key: "centrality not computed", words: "centrality not computed", gap: true });
    }
    reason = `${reason}; centrality not computed for this link`;
  } else {
    reason = `${reason}; measured non-bridge`;
  }

  let strands = 1;
  if (link.isPortChannel) {
    if (link.members.length >= 2) {
      strands = Math.min(4, link.members.length);
    } else {
      // A port channel has at least two members by definition, so a member list this short is a
      // gap in the record rather than a one-member bundle. Draw a bundle, claim no count.
      strands = 2;
      notObserved.push("port-channel member count");
    }
    reason = `${reason}; port channel`;
  }

  const roleOnly = colorToken === "--link-bridge";
  return { linkId: link.id, widthPx, colorToken, dash, strands, doubled, roleOnly, notObserved, reason, drawnClaims };
}

/* ── routing ───────────────────────────────────────────────────────────────── */

const _a = new Vector3();
const _b = new Vector3();
const _mid = new Vector3();
const _p = new Vector3();
const _q = new Vector3();

/**
 * Move an endpoint from the node centre out to the chassis surface, facing the far end.
 *
 * Without this every cable vanishes into the middle of a box and the fabric reads as a wire
 * diagram with boxes dropped on top. The intersection is done against the axis-aligned half-extents
 * in the XZ plane, which is exact for the rack-mount kinds and a close enough circumscription for
 * the lathed access point.
 */
export function surfaceAnchor(
  centre: Vec3,
  half: readonly [number, number, number],
  towards: Vec3,
  out: Vector3,
): Vector3 {
  const dx = towards[0] - centre[0];
  const dz = towards[2] - centre[2];
  const len = Math.hypot(dx, dz);
  if (len < 1e-6) {
    return out.set(centre[0], centre[1], centre[2] + half[2] + 0.4);
  }
  const ux = dx / len;
  const uz = dz / len;
  // Slab intersection: the smaller of the two axis crossings is the face the ray actually leaves by.
  const tx = Math.abs(ux) < 1e-6 ? Infinity : half[0] / Math.abs(ux);
  const tz = Math.abs(uz) < 1e-6 ? Infinity : half[2] / Math.abs(uz);
  const t = Math.min(tx, tz) + 0.45;
  // Slightly below the centre plane: cables leave a chassis at its ports, not through its lid.
  return out.set(centre[0] + ux * t, centre[1] - half[1] * 0.22, centre[2] + uz * t);
}

const _towardsA: [number, number, number] = [0, 0, 0];
const _towardsB: [number, number, number] = [0, 0, 0];

/**
 * Anchor BOTH ends of a link, which is not the same as anchoring each end independently.
 *
 * `surfaceAnchor` picks the face an end leaves by from the XZ direction to the other end. That is
 * right until the two chassis are STACKED — one tier directly above the other, as `dist1`/`podacc1`
 * and `dist2`/`podacc2` are in this snapshot (XZ offsets under half a unit, 64 units apart in Y).
 * Then the direction is noise, and the two ends take OPPOSITE faces: podacc1 left by its −X face,
 * dist1 by its +X face, and the cable ran diagonally across podacc1's whole footprint while it
 * climbed. MEASURED (render audit #8 + a sampled-polyline probe): 13 of 29 samples of L39 and 12 of
 * 29 of L43 lay inside their own endpoint's footprint above its lid, which is the cable seen
 * running across the lid and cut off where it met the chassis — the reverse of "cables leave a
 * chassis at its ports, not through its lid". Every other link in the snapshot was clear.
 *
 * So when the two footprints overlap in plan, both ends leave by the SAME side and the cable rises
 * beside the stack instead of across it. The side follows the sign of the residual X offset, so it
 * is deterministic and still a function of the data.
 */
export function anchorLink(
  a: { centre: Vec3; half: readonly [number, number, number] },
  b: { centre: Vec3; half: readonly [number, number, number] },
  outA: Vector3,
  outB: Vector3,
): Vector3 {
  const dx = b.centre[0] - a.centre[0];
  const dz = b.centre[2] - a.centre[2];
  const stacked = Math.abs(dx) < a.half[0] + b.half[0] && Math.abs(dz) < a.half[2] + b.half[2];
  if (!stacked) {
    surfaceAnchor(a.centre, a.half, b.centre, outA);
    surfaceAnchor(b.centre, b.half, a.centre, outB);
    return outA;
  }
  const side = dx >= 0 ? 1 : -1;
  _towardsA[0] = a.centre[0] + side * 1000;
  _towardsA[1] = a.centre[1];
  _towardsA[2] = a.centre[2];
  _towardsB[0] = b.centre[0] + side * 1000;
  _towardsB[1] = b.centre[1];
  _towardsB[2] = b.centre[2];
  surfaceAnchor(a.centre, a.half, _towardsA, outA);
  surfaceAnchor(b.centre, b.half, _towardsB, outB);
  /* Both ends on the OUTER envelope of the stack: with the residual offset, the nearer face of one
     chassis sits inside the other's footprint by that offset, and the riser would graze its lid. */
  const x = side > 0 ? Math.max(outA.x, outB.x) : Math.min(outA.x, outB.x);
  outA.x = x;
  outB.x = x;
  return outA;
}

/**
 * Sample a cable into a polyline.
 *
 * A straight segment between two boxes reads as a schematic connector; a curve reads as a cable.
 * The curve is a quadratic Bezier whose control point is the layout's own route hint when one
 * exists — `layout.ts` computes those precisely so a cable arcs AROUND an intervening tier rather
 * than through it — and otherwise the midpoint pulled down by a sag proportional to span, which is
 * what an unsupported cable actually does. The sag is capped well below the 64-unit tier pitch so
 * it can never reach the deck below.
 */
export function routeCable(
  from: Vector3,
  to: Vector3,
  hint: Vec3 | null,
  segments: number,
  out: Float32Array,
): number {
  _a.copy(from);
  _b.copy(to);
  if (hint !== null) {
    _mid.set(hint[0], hint[1], hint[2]);
  } else {
    const span = Math.hypot(_b.x - _a.x, _b.z - _a.z);
    const sag = Math.min(11, Math.max(1.6, span * 0.085));
    _mid.addVectors(_a, _b).multiplyScalar(0.5);
    _mid.y -= sag;
  }
  // Quadratic Bezier, unrolled: a CatmullRomCurve3 would allocate a Vector3 per sample, and this
  // runs for every link every time the topology or quality tier changes.
  for (let i = 0; i <= segments; i += 1) {
    const t = i / segments;
    const it = 1 - t;
    const w0 = it * it;
    const w1 = 2 * it * t;
    const w2 = t * t;
    out[i * 3] = w0 * _a.x + w1 * _mid.x + w2 * _b.x;
    out[i * 3 + 1] = w0 * _a.y + w1 * _mid.y + w2 * _b.y;
    out[i * 3 + 2] = w0 * _a.z + w1 * _mid.z + w2 * _b.z;
  }
  return segments + 1;
}

/* ── batching ──────────────────────────────────────────────────────────────── */

/**
 * One draw call per (dash style, width) pair. Colour varies per segment through the instance colour
 * attribute, so a batch holds many differently coloured links; width and dash are material uniforms
 * and therefore have to partition the batches.
 */
export interface CableBatch {
  key: string;
  object: LineSegments2;
  material: LineMaterial;
  /** Link id for every segment, parallel to the geometry's instance array — the pick mapping. */
  segmentLinkIds: string[];
  /** Per-segment recession, 0 = fully present. Shared buffer; write then flag once. */
  recede: InstancedBufferAttribute;
}

export interface CableSet {
  batches: CableBatch[];
  visuals: Map<string, LinkVisual>;
  /** First and last sampled point of each link's primary strand, for trace anchoring. */
  endpoints: Map<string, { a: Vector3; b: Vector3 }>;
  /** Every sampled point of each link's primary strand, so a trace can follow the real cable. */
  polylines: Map<string, Float32Array>;
  setResolution(width: number, height: number): void;
  retint(tokens: TokenPalette): void;
  dispose(): void;
}

const DASH_PARAMS: Readonly<Record<DashStyle, { dashSize: number; gapSize: number }>> = Object.freeze({
  // World units, scaled from design-brief.md §4.5 by the ratio between this fabric's ~330-unit
  // span and the ~140-unit scene the brief's figures were written against.
  solid: { dashSize: 1, gapSize: 0 },
  dashed: { dashSize: 3.8, gapSize: 2.6 },
  /* Deviates from the brief's scaled 0.83 / 2.36. At the overview dolly that dot was ~1 px long, so
     SMAA treated each one as an isolated speck and blended it into the ground: MEASURED (audit D4)
     the dotted core2→wan-edge link peaked at 1.09:1 light / 1.92:1 dark. A dot must be long enough
     to keep one full-ink pixel after the AA pass; it reads as dotted beside `short` (7.2/1.8, mostly ink)
     because its gap is nearly twice its dash. */
  dotted: { dashSize: 1.8, gapSize: 2.8 },
  /* Deviates from the brief's short-dash 1.0 / 1.0 (and from the 2.4 / 2.4 that replaced it).
     MEASURED (independent audit D8, legend + fabric under html{filter:grayscale(1)}): "centrality
     not computed" at 2.4 / 2.4 and "state unknown" dotted at 1.8 / 2.8 were both thin broken
     lines of about the same period, so in greyscale the two states differed only by hue. This is
     now a LONG dash with a short gap — a line that is mostly ink, broken by ticks — which is the
     opposite silhouette to dotted (mostly gap) and a different ratio from `dashed` (down, 3.8 /
     2.6), so all four operational/centrality patterns read by shape alone. */
  short: { dashSize: 7.2, gapSize: 1.8 },
});

/**
 * Every link is painted at FULL opacity, and that is a deliberate departure from
 * design-brief.md §4.5's "ordinary link at 55 %".
 *
 * WCAG 1.4.11 covers graphical objects, and a canvas is not exempt — the brief says so itself and
 * publishes the measured ratios. But those ratios are measured on SOLID colours: it quotes a
 * dimmed off-path link as `#5c6678` on `#0a0d13`, 3.36:1. Compositing `--claim-out-of-scope` at
 * 55 % alpha over the stage does not produce that colour; it produces roughly `#3a4351`, about
 * 2.0:1, which fails. So the hierarchy the 55 % was buying is bought instead by the recession
 * channel, which dims off-path links only when there IS an on-path subject to contrast them
 * against. With nothing selected every link is legible; with a trace up, the trace is loudest.
 */
const BASE_OPACITY = 1;
const ORDINARY_OPACITY = 1;

export interface CableMaterialOptions {
  /**
   * Per-segment colour from `instanceColorStart/End`. MUST be false for a geometry that does not
   * carry those attributes: LineMaterial's shader multiplies by `vColor` under `USE_COLOR`, and an
   * absent attribute reads as zero, so the line renders BLACK with no error anywhere. That is
   * exactly how the trace path first shipped.
   */
  vertexColors?: boolean;
  /** Parallel rails drawn by this one stroke, each `widthPx` wide (default 1). */
  rails?: number;
  /** Gap between rails, in CSS pixels. */
  railGapPx?: number;
}

export function createCableMaterial(
  dash: DashStyle,
  widthPx: number,
  opacity: number,
  opts: CableMaterialOptions = {},
): LineMaterial {
  const params = DASH_PARAMS[dash];
  const rails = Math.max(1, Math.round(opts.rails ?? 1));
  const gapPx = rails > 1 ? Math.max(STRAND_RAIL_GAP_PX, opts.railGapPx ?? STRAND_RAIL_GAP_PX) : 0;
  /* THE STROKE FLOOR, held HERE because this is the one constructor of every stroke the fabric
     draws — cables, the uncollected outline, the trace path, its blocked segment and its tether
     (stroke-floor.test.ts walks the built scene and the source to keep it the only one). The
     callers used to ask for 1.4 (the uncollected outline) and 1.5 (the tether), under
     design-brief §4.5's "Minimum painted stroke is 2 CSS px". A request below the floor gets the
     floor; a caller cannot opt a stroke out of it. */
  const railPx = Math.max(MIN_STROKE_PX, widthPx);
  const nominalPx = rails * railPx + (rails - 1) * gapPx;
  const mat = new LineMaterial({
    color: 0xffffff,
    // + CABLE_EDGE_AA_PX so the coverage ramp is added outside the encoded width, not taken
    // out of it. See the constant: the ink this carries is exactly railPx per rail.
    linewidth: nominalPx + CABLE_EDGE_AA_PX,
    worldUnits: false,
    vertexColors: opts.vertexColors !== false,
    transparent: true,
    /* NO DEPTH WRITE — the C5 "1 px dashed hairline" (acceptance report at 70bea72, item 8).
       A stroke's quad is wider than its ink: it carries the anti-alias margin and, on a multi-rail
       cable, the gaps between rails, and those fragments paint nothing (coverage 0) or next to
       nothing. A depth write is not coverage-weighted, so with it on they still stamped the depth
       buffer, and a parallel cable of the same bundle drawn later and a hair farther away failed
       the depth test everywhere its neighbour's quad lay. IDENTIFIED on the core2 bundle (overview,
       1440x900 DSF 2): a 2 px rail of an unobserved-speed bridge (`cables:solid|2|1|2x3`) was cut
       to ONE device pixel by its neighbour's rail gap, and because which of the two is nearer
       flips segment by segment the survivor read as a dashed hairline. Discarding the zero-
       coverage fragments alone was tried and left a dark dashed seam wherever a partially covered
       edge pixel occluded the neighbour behind it. The deck planes had the same disease
       (materials.ts, "A depth write is not alpha-weighted") and the same cure. The depth TEST
       stays on, so the opaque chassis still hide every stroke behind them. */
    depthWrite: false,
    dashed: dash !== "solid",
    dashScale: 1,
    dashSize: params.dashSize,
    gapSize: params.gapSize,
    opacity,
  });
  /* `alphaToCoverage` is NOT set here, and the claim that used to sit on this line — that it "is
   * what removes the stair-stepping from long diagonal cable runs" — was false and is recorded as
   * such rather than quietly deleted.
   *
   * Read three 0.186.0's LineMaterial shader: the `USE_ALPHA_TO_COVERAGE` branch replaces a
   * `discard` with a smoothstep ONLY inside `if (abs(vUv.y) > 1.0)`, i.e. only on the ROUND CAP at
   * each end of a segment. The long edges of the segment body are the rasterised edges of a
   * camera-facing quad and are untouched by it. There was never an analytic coverage term on the
   * thing the comment named.
   *
   * MEASURED (review/_audit_cableaa.mjs, real GPU, dark, tier high, the cable-over-background band
   * y 270-345): with it ON, 675 of 876 background-to-cable crossings were zero-intermediate hard
   * steps; with it OFF, 609 of 828 — 77.1 % against 73.6 %. It was slightly WORSE than nothing,
   * which is what an unused multisample coverage path does when the composer runs multisampling: 0.
   * The stair-stepping is fixed in postfx.ts, by feeding SMAA an image it can actually read. */
  /* Display-linear edge coverage (see coverageGamma). 1 until the owner of the palette sets it:
     buildCables does, for every batch, and re-fits it in retint. */
  mat.uniforms.coverageGamma = { value: 1 };
  patchRecession(mat, nominalPx, rails > 1 ? { rails, railPx, gapPx } : null);
  return mat;
}

/**
 * Teach a LineMaterial two things it does not know: the per-segment recession channel, and how to
 * anti-alias its own long edges.
 *
 * Patched by string surgery on the shader source rather than through `onBeforeCompile`, because
 * LineMaterial is a ShaderMaterial whose source we own outright here; editing the strings keeps the
 * whole transformation visible in one place instead of split across a callback and a cache key.
 *
 * ── THE EDGE COVERAGE TERM, and why the library has no equivalent ───────────────────────────────
 *
 * Read three 0.186.0's LineMaterial fragment shader. In the screen-space (non-WORLD_UNITS) path,
 * `vUv.x` is the ACROSS-WIDTH coordinate and `vUv.y` runs ALONG the segment — which you can read
 * straight off the endcap test, `a = vUv.x; b = vUv.y -/+ 1; if (a*a + b*b > 1.0) discard`, a unit
 * circle centred on each segment END. Every smoothing term the library has, `alphaToCoverage`
 * included, lives inside `if (abs(vUv.y) > 1.0)` — i.e. it applies ONLY to the round caps. The two
 * long edges of the stroke, which are essentially all of a cable's visible perimeter, are the raw
 * rasterised edges of a camera-facing quad and get nothing at all.
 *
 * That is why the fabric's dominant geometry was stair-stepped no matter what the post chain did:
 * SMAA was being asked to reconstruct an edge from a 1.5-3 px stroke, which is below the several
 * consistent pixels its pattern classifier needs.
 *
 * So the coverage is computed where it is known exactly. `fwidth(vUv.x)` is the width of one pixel
 * measured in the same units the edge is expressed in, so the ramp is always one pixel wide
 * whatever the dolly, the line width or the device pixel ratio. It fades INWARD from the quad
 * boundary rather than straddling it, because fragments outside the quad do not exist to be shaded.
 *
 * MEASURED, review/_audit_cableaa.mjs at `high` on a real GPU, background-to-cable crossings that
 * are zero-intermediate hard steps: see docs/render-decisions.md for the full table.
 */
function patchRecession(
  mat: LineMaterial,
  nominalWidthPx: number,
  railSpec: { rails: number; railPx: number; gapPx: number } | null = null,
): void {
  /* Where the NOMINAL edge sits in the drawn quad. vUv.x spans [-1, 1] over the drawn half-width,
     which is (nominalWidthPx + CABLE_EDGE_AA_PX) / 2, so the encoded edge is at this fraction. */
  const edgeU = nominalWidthPx / (nominalWidthPx + CABLE_EDGE_AA_PX);
  mat.vertexShader = mat.vertexShader
    .replace(
      "attribute vec3 instanceStart;",
      `attribute vec3 instanceStart;\n\t\tattribute float aRecede;\n\t\tvarying float vRecede;\n\t\tattribute vec3 ${RECEDE_INK_ATTRIBUTE};\n\t\tvarying vec3 vRecedeInk;`,
    )
    .replace(
      "float aspect = resolution.x / resolution.y;",
      `vRecede = aRecede;\n\t\t\tvRecedeInk = ${RECEDE_INK_ATTRIBUTE};\n\t\t\tfloat aspect = resolution.x / resolution.y;`,
    );
  mat.fragmentShader = mat.fragmentShader
    .replace(
      "uniform vec3 diffuse;",
      "uniform vec3 diffuse;\n\t\tuniform float coverageGamma;\n\t\tvarying float vRecede;\n\t\tvarying vec3 vRecedeInk;",
    )
    .replace(
      "gl_FragColor = vec4( diffuseColor.rgb, alpha );",
      [
        /* Recession is a COLOUR, never an alpha (see `cableInk`): it walks from the segment's ink
           to its receded ink, both precomputed per token to clear their own contrast floors. It
           used to thin alpha and dim radiance toward black, which on the light stage blended the
           backdrop's ~5-linear pre-image into the cable and measured 1.09-1.49:1. Normalised so the
           deepest recession the emphasis pass asks for lands exactly on the receded ink. A line
           with no recession attribute (trace, blocked segment, wireframe) reads 0 and is exact. */
        `float _r = clamp( vRecede / ${RECEDE_DEPTH.toFixed(4)}, 0.0, 1.0 );`,
        "vec3 _rgb = mix( diffuseColor.rgb, vRecedeInk, _r );",
        /* A cable is a round thing lit from above, not a flat vector stroke: a cheap cylindrical
           term across the width — the ink exactly on the crown, darker toward both edges. The
           crown carries the ink unmodified, so the contrast floor is held by every stroke's
           strongest pixel. */
        `float _u = clamp( abs( vUv.x ) / ${edgeU.toFixed(5)}, 0.0, 1.0 );`,
        `_rgb *= mix( ${CABLE_TUBE_EDGE.toFixed(3)}, 1.0, sqrt( max( 0.0, 1.0 - _u * _u ) ) );`,
        /* One device pixel, measured in the coordinate the stroke's edge is expressed in. The
           gradient LENGTH, not fwidth: fwidth is |dFdx| + |dFdy|, which overstates a pixel by up to
           sqrt(2) on a diagonal cable and so thinned every diagonal stroke's opaque core. */
        "float _px = max( length( vec2( dFdx( vUv.x ), dFdy( vUv.x ) ) ), 1e-5 );",
        /* Coverage, in device pixels from the centreline. A one-pixel filter centred ON the nominal
           edge — half inside the stroke, half in the margin the quad was widened by — so the ink
           carried is the encoded width. But the OPAQUE CORE never falls below one device pixel.
           The previous 1.6 px filter was wider than the thinnest encoded stroke (1.5 px, "speed
           not observed"), so that class had no opaque pixel at all; every pixel of it was a
           partial-coverage blend. And a partial blend here is not a mild tint: it happens in the
           LINEAR HDR buffer before AgX, where the light stage's pre-image is ~5, so 40 % of the
           ground made the pixel almost the ground. MEASURED (audit D4): the dashed fan's strongest
           pixel was 1.25:1. Every class now carries at least one full-ink pixel across its width,
           which is what the contrast floor in `cableInk` is a floor FOR. */
        "float _dist = abs( vUv.x ) / _px;",
        `float _core = max( ${edgeU.toFixed(5)} / _px - 0.5, 0.5 );`,
        "float _cov = clamp( _core + 1.0 - _dist, 0.0, 1.0 );",
        ...(railSpec === null ? [] : railCut(railSpec, nominalWidthPx)),
        /* Coverage is geometric; what the reader sees is the tone-mapped blend. Re-shaped so a pixel's
           DISPLAYED position between ground and ink tracks its coverage (coverageGamma): without it the
           light stage's fringe washed out and its cables landed ~1 px wide. 0 and 1 are fixed points,
           so the opaque core and the outside of the stroke are untouched. */
        "_cov = pow( _cov, coverageGamma );",
        /* NO ROUND CAPS INSIDE A CABLE (C5 motion, 2026-09-22). A cable is a polyline of short
           segments, and LineMaterial gives every segment a round cap, so consecutive segments OVERLAP
           at every joint. Both overlapping fragments are nearly the same depth, and which one is
           nearer flips as the camera creeps; the partially-covered edge pixels there are then blended
           once or twice on alternate frames. MEASURED with review/capture-motion.mjs's orbit-keys-slow
           replay: the remaining flip-flop cluster (9 x 7 px on a cable fan, two segments of one batch
           0.02 units apart along the ray) appeared in ~2 of 3 runs with caps and in 0 of 4 without.
           The joints between segments of a gently curved cable need no cap: the outer-side wedge a
           5-degree bend leaves is under a tenth of a pixel. */
        "if ( abs( vUv.y ) > 1.0 ) discard;",
        "gl_FragColor = vec4( _rgb, alpha * _cov );",
      ].join("\n\t\t\t"),
    );
  mat.needsUpdate = true;
}

/**
 * GLSL that cuts a multi-rail stroke into its rails (see BRIDGE_RAIL_GAP_PX). Runs after the outer
 * coverage and tube term of the single-rail path, and replaces the tube term with one per rail so
 * each rail keeps its own lit crown. Positions are in CSS pixels across the nominal width; one
 * device pixel in the same units is `_px` scaled by the drawn half-width, so the gap edges get the
 * same one-device-pixel filter as the outer edges.
 */
function railCut(spec: { rails: number; railPx: number; gapPx: number }, nominalPx: number): string[] {
  const half = (nominalPx + CABLE_EDGE_AA_PX) / 2;
  const pitch = spec.railPx + spec.gapPx;
  const f = (n: number): string => n.toFixed(5);
  return [
    `float _cssPerU = ${f(half)};`,
    "float _dpx = max( _px * _cssPerU, 1e-4 );",
    `float _t = vUv.x * _cssPerU + ${f(nominalPx / 2)};`,
    `float _tt = clamp( _t, 0.0, ${f(nominalPx)} );`,
    `float _loc = mod( _tt, ${f(pitch)} );`,
    // Signed distance into the nearest rail (negative inside a gap), in CSS px.
    `float _sd = _loc < ${f(spec.railPx)} ? min( _loc, ${f(spec.railPx)} - _loc ) : -min( _loc - ${f(spec.railPx)}, ${f(pitch)} - _loc );`,
    "_sd -= abs( _t - _tt );",
    "_cov = min( _cov, clamp( _sd / _dpx + 0.5, 0.0, 1.0 ) );",
    `float _ru = clamp( abs( min( _loc, ${f(spec.railPx)} ) - ${f(spec.railPx / 2)} ) / ${f(spec.railPx / 2)}, 0.0, 1.0 );`,
    `_rgb = mix( diffuseColor.rgb, vRecedeInk, _r ) * mix( ${CABLE_TUBE_EDGE.toFixed(3)}, 1.0, sqrt( max( 0.0, 1.0 - _ru * _ru ) ) );`,
  ];
}

interface Accum {
  key: string;
  dash: DashStyle;
  widthPx: number;
  opacity: number;
  rails: number;
  gapPx: number;
  positions: number[];
  colors: number[];
  /** Receded ink per segment (one vec3 per instance), parallel to segmentLinkIds. */
  recededInks: number[];
  distances: number[];
  segmentLinkIds: string[];
}

export interface CableBuildInput {
  links: readonly Link[];
  /** Node centre and half-extents for both ends; a link naming an unplaced host is skipped. */
  anchorOf(host: string): { centre: Vec3; half: readonly [number, number, number] } | null;
  midpointOf(linkId: string): Vec3 | null;
  segments: number;
  tokens: TokenPalette;
}

export function buildCables(input: CableBuildInput): CableSet {
  const { links, segments, tokens } = input;
  const visuals = new Map<string, LinkVisual>();
  const endpoints = new Map<string, { a: Vector3; b: Vector3 }>();
  const polylines = new Map<string, Float32Array>();
  const accum = new Map<string, Accum>();
  const inkOf = inkTable(tokens);
  const sample = new Float32Array((segments + 1) * 3);

  for (const link of links) {
    const av = input.anchorOf(link.a);
    const bv = input.anchorOf(link.b);
    if (av === null || bv === null) continue; // layout.diagnostics.linksWithUnplacedEndpoint owns this

    const visual = classifyLink(link);
    visuals.set(link.id, visual);

    anchorLink(av, bv, _p, _q);
    const count = routeCable(_p, _q, input.midpointOf(link.id), segments, sample);
    polylines.set(link.id, sample.slice(0, count * 3));
    endpoints.set(link.id, { a: _p.clone(), b: _q.clone() });

    const { ink: colour, receded } = inkOf(visual.colorToken, restChromaOf(visual));
    const opacity =
      visual.colorToken === "--claim-out-of-scope" ? ORDINARY_OPACITY : BASE_OPACITY;
    const { rails, gapPx } = railsOf(visual);
    const key = `${visual.dash}|${visual.widthPx}|${opacity}|${rails}x${gapPx}`;
    let bucket = accum.get(key);
    if (bucket === undefined) {
      bucket = {
        key,
        dash: visual.dash,
        widthPx: visual.widthPx,
        opacity,
        rails,
        gapPx,
        positions: [],
        colors: [],
        recededInks: [],
        distances: [],
        segmentLinkIds: [],
      };
      accum.set(key, bucket);
    }

    /* Strands and bridge rails are cut in SCREEN space by the material (railsOf), so every link is
       one centreline polyline here: a world-unit offset is only a gap at some dolly. */
    {
      // Distance resets to zero at the start of every strand, so a dash pattern begins at the
      // chassis instead of inheriting a phase from whichever link was batched before it.
      let run = 0;
      for (let i = 0; i < count - 1; i += 1) {
        const x0 = sample[i * 3] ?? 0;
        const y0 = sample[i * 3 + 1] ?? 0;
        const z0 = sample[i * 3 + 2] ?? 0;
        const x1 = sample[(i + 1) * 3] ?? 0;
        const y1 = sample[(i + 1) * 3 + 1] ?? 0;
        const z1 = sample[(i + 1) * 3 + 2] ?? 0;
        const segLen = Math.hypot(x1 - x0, y1 - y0, z1 - z0);
        bucket.positions.push(x0, y0, z0, x1, y1, z1);
        bucket.colors.push(colour.r, colour.g, colour.b, colour.r, colour.g, colour.b);
        bucket.recededInks.push(receded.r, receded.g, receded.b);
        bucket.distances.push(run, run + segLen);
        bucket.segmentLinkIds.push(link.id);
        run += segLen;
      }
    }
  }

  const batches: CableBatch[] = [];
  for (const bucket of accum.values()) {
    const geometry = new LineSegmentsGeometry();
    geometry.setPositions(new Float32Array(bucket.positions));
    geometry.setColors(new Float32Array(bucket.colors));
    const distanceBuffer = new InstancedInterleavedBuffer(new Float32Array(bucket.distances), 2, 1);
    geometry.setAttribute("instanceDistanceStart", new InterleavedBufferAttribute(distanceBuffer, 1, 0));
    geometry.setAttribute("instanceDistanceEnd", new InterleavedBufferAttribute(distanceBuffer, 1, 1));
    const recede = new InstancedBufferAttribute(new Float32Array(bucket.segmentLinkIds.length), 1);
    recede.setUsage(DynamicDrawUsage);
    geometry.setAttribute(
      RECEDE_INK_ATTRIBUTE,
      new InstancedBufferAttribute(new Float32Array(bucket.recededInks), 3),
    );
    geometry.setAttribute(RECEDE_ATTRIBUTE, recede);

    const material = createCableMaterial(bucket.dash, bucket.widthPx, bucket.opacity, {
      rails: bucket.rails,
      railGapPx: bucket.gapPx,
    });
    setCoverageGamma(material, coverageGamma(tokens));
    const object = new LineSegments2(geometry, material);
    object.name = `cables:${bucket.key}`;
    object.frustumCulled = false; // a single batch spans the whole fabric; its bounds are never off-screen
    object.castShadow = false;
    object.receiveShadow = false;
    // Cables draw after the opaque chassis so their blended edges composite against a finished
    // frame rather than against whatever happened to be rasterised first.
    object.renderOrder = 2;
    batches.push({ key: bucket.key, object, material, segmentLinkIds: bucket.segmentLinkIds, recede });
  }

  const set: CableSet = {
    batches,
    visuals,
    endpoints,
    polylines,
    setResolution(width: number, height: number): void {
      for (const b of batches) b.material.resolution.set(width, height);
    },
    retint(next: TokenPalette): void {
      const nextInk = inkTable(next);
      const gamma = coverageGamma(next);
      for (const b of batches) {
        setCoverageGamma(b.material, gamma);
        const colours = b.object.geometry.getAttribute("instanceColorStart") as
          | InterleavedBufferAttribute
          | undefined;
        const ends = b.object.geometry.getAttribute("instanceColorEnd") as
          | InterleavedBufferAttribute
          | undefined;
        const recededInks = b.object.geometry.getAttribute(RECEDE_INK_ATTRIBUTE) as
          | InstancedBufferAttribute
          | undefined;
        if (colours === undefined || ends === undefined) continue;
        for (let i = 0; i < b.segmentLinkIds.length; i += 1) {
          const id = b.segmentLinkIds[i];
          const v = id === undefined ? undefined : set.visuals.get(id);
          if (v === undefined) continue;
          // Both inks are re-resolved against the NEW ground: a floor held on one stage says
          // nothing about the other.
          const { ink: c, receded: rc } = nextInk(v.colorToken, restChromaOf(v));
          colours.setXYZ(i, c.r, c.g, c.b);
          ends.setXYZ(i, c.r, c.g, c.b);
          recededInks?.setXYZ(i, rc.r, rc.g, rc.b);
        }
        colours.needsUpdate = true;
        ends.needsUpdate = true;
        if (recededInks !== undefined) recededInks.needsUpdate = true;
      }
    },
    dispose(): void {
      for (const b of batches) {
        b.object.geometry.dispose();
        b.material.dispose();
        b.object.removeFromParent();
      }
      batches.length = 0;
    },
  };
  return set;
}
