/**
 * cables.ink.test.ts — the cable contrast floor (audit D4, WCAG 1.4.11).
 *
 * MEASURED before the fix: with a finding selected, off-subject cables reached the screen at
 * 1.09-1.49:1 on the light stage and 1.92-2.67:1 on the dark one. The tokens passed on paper; the
 * pipeline (tokens fed raw into AgX, recession by alpha against an HDR backdrop pre-image) did not.
 *
 * These tests pin the arithmetic without a GPU, for EVERY token a cable can be painted in and
 * against BOTH stages: what AgX puts on screen for the ink and for the receded ink clears its
 * floor against the worst end of the backdrop gradient. The rendered pixel itself is measured by
 * review/_r3d_scan.mjs (see docs/render-decisions.md) — this is the ratchet, not the evidence.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { Color } from "three";
import { agxInverse } from "../env";
import {
  buildCables,
  coverageGamma,
  CABLE_INK_FLOOR,
  CABLE_RECEDED_FLOOR,
  cableGround,
  cableInk,
  classifyLink,
  contrastOfLuminance,
  createCableMaterial,
  displayedLuminance,
  RECEDE_INK_ATTRIBUTE,
} from "./cables";
import { readTokens, type ThemeName, type TokenPalette } from "../materials";
import type { Link } from "../../core/types";

/** Every colour token classifyLink can emit — derived by running it, not by listing names. */
function cableTokens(): string[] {
  const out = new Set<string>();
  const statuses = ["up", "down", "unknown", "admin-down"];
  const bridges = [true, false, null];
  for (const opStatus of statuses) {
    for (const isBridge of bridges) {
      const link = {
        id: "L",
        a: "a",
        b: "b",
        speedMbps: 1000,
        opStatus,
        isBridge,
        isPortChannel: false,
        members: [],
      } as unknown as Link;
      out.add(classifyLink(link).colorToken);
    }
  }
  return [...out];
}

/** The palette the app actually ships: tokens.css parsed for each theme's first declaration block. */
function shippedPalette(theme: ThemeName): TokenPalette {
  const css = readFileSync(resolve(__dirname, "../../core/tokens.css"), "utf8");
  const host = document.createElement("div");
  // The first `:root {` block is the light palette; the dark overrides live under a media query or
  // [data-theme="dark"]. Apply the declarations the way the cascade would for each theme.
  const decls = (block: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const m of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      const k = m[1];
      const v = m[2];
      if (k !== undefined && v !== undefined) out[k] = v.replace(/\/\*.*?\*\//g, "").trim();
    }
    return out;
  };
  const rootBlock = /^:root\s*\{([\s\S]*?)\n\}/m.exec(css)?.[1] ?? "";
  const darkBlock = /^\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/m.exec(css)?.[1] ?? "";
  expect(rootBlock.length).toBeGreaterThan(100);
  if (theme === "dark") expect(darkBlock.length).toBeGreaterThan(100);
  const vars = { ...decls(rootBlock), ...(theme === "dark" ? decls(darkBlock) : {}) };
  for (const [k, v] of Object.entries(vars)) host.style.setProperty(k, v);
  document.body.appendChild(host);
  try {
    return readTokens(theme, host);
  } finally {
    host.remove();
  }
}

const palettes: Array<[string, TokenPalette]> = [];
for (const theme of ["light", "dark"] as const) {
  palettes.push([`${theme} (built-in fallback)`, readTokens(theme)]);
  palettes.push([`${theme} (shipped tokens.css)`, shippedPalette(theme)]);
}

describe("cable ink holds its contrast floor after the tone map", () => {
  const tokens = cableTokens();

  it("derives a non-trivial token set from classifyLink", () => {
    expect(tokens.length).toBeGreaterThanOrEqual(4);
  });

  for (const [name, palette] of palettes) {
    for (const token of tokens) {
      it(`${name}: ${token} ink ≥ ${CABLE_INK_FLOOR}:1 and receded ≥ ${CABLE_RECEDED_FLOOR}:1`, () => {
        const ground = cableGround(palette);
        const ink = cableInk(palette, token);
        const inkRatio = contrastOfLuminance(displayedLuminance(ink.ink), ground.y);
        const recRatio = contrastOfLuminance(displayedLuminance(ink.receded), ground.y);
        // 0.1 of slack for the fixed-point AgX inverse; the design floors carry more than that.
        expect(inkRatio).toBeGreaterThanOrEqual(CABLE_INK_FLOOR - 0.1);
        expect(recRatio).toBeGreaterThanOrEqual(CABLE_RECEDED_FLOOR - 0.1);
        // Receding must never make a cable LOUDER than it is at full presence.
        expect(recRatio).toBeLessThanOrEqual(inkRatio + 0.05);
        // And receding must actually RECEDE: an ink above the receded floor lands on it. (A
        // direction bug once left dark-stage recession a no-op and every assertion above passed.)
        if (inkRatio > CABLE_RECEDED_FLOOR + 0.2) {
          expect(recRatio).toBeLessThan(CABLE_RECEDED_FLOOR + 0.2);
        }
        // And both still sit on the ink's side of the ground (dark ink on the pale stage).
        const inkY = displayedLuminance(ink.ink);
        expect(ground.inkDarker ? inkY < ground.y : inkY > ground.y).toBe(true);
      });
    }
  }

  it("the shipped palettes were actually parsed (the ratchet is not testing only fallbacks)", () => {
    for (const theme of ["light", "dark"] as const) {
      expect(shippedPalette(theme).missing).toEqual([]);
    }
  });
});

describe("the cable shader carries recession as colour, not alpha", () => {
  it("declares the receded-ink attribute and never thins alpha by recession", () => {
    const mat = createCableMaterial("solid", 1.5, 1);
    try {
      expect(mat.vertexShader).toContain(`attribute vec3 ${RECEDE_INK_ATTRIBUTE}`);
      expect(mat.fragmentShader).toContain("mix( diffuseColor.rgb, vRecedeInk, _r )");
      expect(mat.fragmentShader).toContain("gl_FragColor = vec4( _rgb, alpha * _cov );");
      // The thinnest class keeps an opaque core of at least one device pixel.
      expect(mat.fragmentShader).toMatch(/max\( [\d.]+ \/ _px - 0\.5, 0\.5 \)/);
    } finally {
      mat.dispose();
    }
  });
});


/* ── C5 "1px hairline links" in the light theme: coverage must be linear on SCREEN ──────────────
 *
 * MEASURED (2026-09-22, the home view at high, DPR 1, scanlines y=230/300/380/460 across every cable
 * crossing): light-theme cables landed with a median coverage-integrated width of 1.83 px and a
 * one-pixel core on 32 of 72 crossings; the same cables on the dark stage, 2.76 px and 2 of 51.
 * Nominal widths are 2.0-3.8 px. The cause is where the edge coverage is blended: in the composer's
 * LINEAR HDR buffer, BEFORE AgX. The light ground's pre-image is ~3.6 and a dark ink's ~0.03, so a
 * 50 %-covered edge pixel is ~1.8 linear — which AgX still puts on screen almost at the ground: it
 * lands 16-18 % of the way to the ink, and the stroke's anti-aliased fringe vanishes. On the dark
 * stage the same blend lands 63-83 % of the way, so dark strokes read FATTER than encoded.
 *
 * So the coverage is re-shaped before it becomes alpha, by an exponent fitted to the palette's own
 * ground and inks through the real AgX curve (`coverageGamma`), so that a pixel's DISPLAYED position
 * between ground and ink tracks its geometric coverage in both themes. */
describe("C5: a cable's edge coverage is linear in display space on both stages", () => {
  /** Where a pixel of geometric coverage `c` lands on screen, 0 = ground, 1 = ink. */
  const displayedCoverage = (palette: TokenPalette, token: string, c: number, gamma: number): number => {
    const ground = cableGround(palette);
    const gL = agxInverse([ground.y, ground.y, ground.y]);
    const ink = cableInk(palette, token).ink;
    const iL = [ink.r, ink.g, ink.b];
    const a = Math.pow(c, gamma);
    const out = gL.map((v, k) => v + ((iL[k] ?? 0) - v) * a) as [number, number, number];
    const shown = displayedLuminance(new Color(out[0], out[1], out[2]));
    return (ground.y - shown) / (ground.y - displayedLuminance(ink));
  };
  const tokens = cableTokens();

  for (const [name, palette] of palettes) {
    it(`${name}: a half-covered edge pixel lands within 0.5 +- 0.15 of the way to the ink, for every cable token`, () => {
      const gamma = coverageGamma(palette);
      const off = tokens
        .map((t) => [t, displayedCoverage(palette, t, 0.5, gamma)] as const)
        .filter(([, d]) => Math.abs(d - 0.5) > 0.15)
        .map(([t, d]) => `${t}: ${d.toFixed(2)}`);
      expect(off, `coverageGamma ${gamma}`).toEqual([]);
    });
  }

  it("the defect is real without the correction (the check is not vacuous): light at gamma 1 washes the fringe out", () => {
    const light = readTokens("light");
    expect(Math.max(...tokens.map((t) => displayedCoverage(light, t, 0.5, 1)))).toBeLessThan(0.3);
  });

  it("every cable material the fabric builds applies the palette's gamma, and a theme change re-fits it", () => {
    const mat = createCableMaterial("solid", 2, 1);
    try {
      expect(mat.fragmentShader).toContain("_cov = pow( _cov, coverageGamma );");
      expect(mat.uniforms.coverageGamma?.value).toBe(1);
    } finally {
      mat.dispose();
    }
    const links = [
      { id: "L1", a: "a", b: "b", speedMbps: 1000, opStatus: "up", isBridge: false, isPortChannel: false, members: [] },
      { id: "L2", a: "a", b: "b", speedMbps: null, opStatus: "unknown", isBridge: null, isPortChannel: false, members: [] },
    ] as unknown as Link[];
    const light = readTokens("light");
    const dark = readTokens("dark");
    const set = buildCables({
      links,
      anchorOf: (h) => ({ centre: h === "a" ? [0, 0, 0] : [40, 0, 0], half: [2, 1, 2] }),
      midpointOf: () => null,
      segments: 8,
      tokens: light,
    });
    try {
      expect(set.batches.length).toBeGreaterThan(0);
      for (const b of set.batches) expect(b.material.uniforms.coverageGamma?.value).toBeCloseTo(coverageGamma(light), 5);
      set.retint(dark);
      for (const b of set.batches) expect(b.material.uniforms.coverageGamma?.value).toBeCloseTo(coverageGamma(dark), 5);
      expect(coverageGamma(light)).toBeLessThan(1);
      expect(coverageGamma(dark)).toBeGreaterThan(1);
    } finally {
      set.dispose();
    }
  });
});

describe("C5 motion: consecutive segments of a cable do not overlap at their joints", () => {
  it("every cable stroke discards LineMaterial's round cap before it writes colour", () => {
    /* The joints are where the last flip-flop cluster of the C5 motion harness lived (see the
       comment at the discard in cables.ts: ~2 of 3 runs with caps, 0 of 4 without). */
    for (const [dash, rails] of [["solid", 1], ["dashed", 1], ["solid", 2]] as const) {
      const mat = createCableMaterial(dash, 2.6, 1, { rails });
      try {
        const fs = mat.fragmentShader;
        const discard = fs.indexOf("if ( abs( vUv.y ) > 1.0 ) discard;");
        expect(discard, `${dash} x${rails}`).toBeGreaterThan(0);
        // ...before the colour is written, so a cap fragment never reaches the blend.
        expect(discard).toBeLessThan(fs.indexOf("gl_FragColor = vec4( _rgb, alpha * _cov );"));
      } finally {
        mat.dispose();
      }
    }
  });
});
