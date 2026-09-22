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
import {
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

