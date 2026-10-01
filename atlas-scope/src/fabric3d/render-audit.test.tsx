/**
 * render-audit.test.tsx — regressions for the 3-D render defects an independent render audit found.
 *
 * Each block names the defect it pins. What these do NOT prove is how a frame looks: the blank
 * frame on a tier change and the aliased port bank were measured on a real GPU
 * (review/_audit3_pop.mjs, review/_audit3_crops.mjs); these tests pin the mechanisms that fixed
 * them, so a revert fails here rather than only in a capture.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { FabricA11yTree } from "./FabricA11yTree";
import { FabricLegend } from "./FabricLegend";
import { buildChassis, GRILLE_METAL_UV } from "./geometry/chassis";
import { classifyLink } from "./geometry/cables";
import { GRILLE_SIZE, grilleTile } from "./materials";
import { effectivePixelRatio, MIN_PIXEL_RATIO, profileFor } from "./quality";

describe("the port bank minifies instead of aliasing (C5)", () => {
  it("is ONE textured plate, not a grid of sub-pixel bars", () => {
    const parts = buildChassis("device", { bevelSegments: 1, fineDetail: false });
    try {
      const uv1 = parts.bezel.getAttribute("uv1");
      expect(uv1, "the bezel carries the grille's UV set").toBeDefined();
      // Some vertices tile the grille (the plate: 12 x 2 ports), the rest sit on the metal texel.
      let tiled = 0;
      let metal = 0;
      for (let i = 0; i < uv1.count; i += 1) {
        const u = uv1.getX(i);
        const v = uv1.getY(i);
        if (Math.abs(u - GRILLE_METAL_UV[0]) < 1e-6 && Math.abs(v - GRILLE_METAL_UV[1]) < 1e-6) metal += 1;
        else tiled += 1;
      }
      expect(tiled).toBe(36); // one box: 6 faces x 2 triangles x 3 vertices
      expect(metal).toBeGreaterThan(0);
      let maxU = 0;
      let maxV = 0;
      for (let i = 0; i < uv1.count; i += 1) {
        maxU = Math.max(maxU, uv1.getX(i));
        maxV = Math.max(maxV, uv1.getY(i));
      }
      // Exactly one texture tile per port: 12 columns x 2 rows on a switch.
      expect([maxU, maxV]).toEqual([12, 2]);
    } finally {
      parts.dispose();
    }
  });

  it("samples pure white at the frame's constant UV, so the frame colour is untouched", () => {
    const tile = grilleTile();
    // Bilinear footprint of GRILLE_METAL_UV at mip 0: the two texels either side of it.
    const x = GRILLE_METAL_UV[0] * GRILLE_SIZE - 0.5;
    const y = GRILLE_METAL_UV[1] * GRILLE_SIZE - 0.5;
    for (const tx of [Math.floor(x), Math.ceil(x)]) {
      for (const ty of [Math.floor(y), Math.ceil(y)]) {
        const i = (((ty + GRILLE_SIZE) % GRILLE_SIZE) * GRILLE_SIZE + ((tx + GRILLE_SIZE) % GRILLE_SIZE)) * 4;
        expect(tile[i]).toBe(255);
      }
    }
  });

  it("keeps the low tier at full resolution with real anisotropic filtering", () => {
    const low = profileFor("low");
    expect(low.renderScale).toBe(1);
    expect(low.anisotropy).toBeGreaterThanOrEqual(4);
  });

  it("never renders below min(devicePixelRatio, 2) at ANY tier, on ANY display (C5)", () => {
    // The class, not one field on one tier: every tier x a sweep of real display ratios, through
    // the same function scene.ts sizes the drawing buffer with.
    let checked = 0;
    for (const tier of ["high", "balanced", "low"] as const) {
      for (const dpr of [1, 1.25, 1.5, 1.75, 2, 2.5, 3]) {
        const ratio = effectivePixelRatio(profileFor(tier), dpr);
        expect(ratio, `${tier} at DPR ${dpr}`).toBeGreaterThanOrEqual(Math.min(dpr, MIN_PIXEL_RATIO) - 1e-9);
        checked += 1;
      }
    }
    expect(checked).toBe(21);
    expect(MIN_PIXEL_RATIO).toBe(2);
  });

  it("uses SMAA ULTRA at every tier (brief §4.9 item 2)", () => {
    for (const tier of ["high", "balanced", "low"] as const) {
      const p = profileFor(tier);
      expect(p.smaa, tier).toBe(true);
      expect(p.smaaPreset, tier).toBe(profileFor("high").smaaPreset);
    }
  });
});

describe("a bridge cable is not a severity (C5)", () => {
  it("draws bridges in the link-topology token, never a --sev-* token", () => {
    const bridge = fabric.links.find((l) => l.isBridge === true);
    expect(bridge, "the snapshot has a bridge link to classify").toBeDefined();
    if (!bridge) return;
    const v = classifyLink(bridge);
    expect(v.colorToken).toBe("--link-bridge");
    for (const l of fabric.links) expect(classifyLink(l).colorToken).not.toMatch(/^--sev-/);
  });
});

describe("the legend's rim key matches the rings the scene draws (D8)", () => {
  it("draws Down as a double ring, not a recoloured Up", () => {
    const html = renderToStaticMarkup(
      <FabricLegend id="legend-test" devices={fabric.devices} links={fabric.links} />,
    );
    // The legend is closed by default; open it the way a stored preference would.
    if (!html.includes("Chassis rim")) {
      window.localStorage.setItem("atlas-scope.fabric-legend.open", "1");
    }
    const open = renderToStaticMarkup(
      <FabricLegend id="legend-test" devices={fabric.devices} links={fabric.links} />,
    );
    const row = (name: string): string => {
      const at = open.indexOf(`</svg><span class="fabric3d-legend__text">${name}`);
      expect(at, `legend row ${name}`).toBeGreaterThan(-1);
      return open.slice(open.lastIndexOf("<svg", at), at);
    };
    const up = row("Up");
    const down = row("Down");
    expect((up.match(/<rect/g) ?? []).length).toBe(1);
    expect(down).toContain('data-ring="double"');
    expect((down.match(/<rect/g) ?? []).length).toBe(2);
  });
});

describe("the fabric tree says when a device was never collected (B1/D6)", () => {
  it("puts 'never collected' on every topology-only row, not just 'band not observed'", () => {
    const html = renderToStaticMarkup(
      <FabricA11yTree
        devices={fabric.devices}
        links={fabric.links}
        tiers={[fabric.devices.map((d) => d.host)]}
        visible
        onHide={() => {}}
        onFocusDevice={() => {}}
      />,
    );
    const uncollected = fabric.devices.filter((d) => !d.collected);
    expect(uncollected.length).toBeGreaterThan(0);
    for (const d of uncollected) {
      const at = html.indexOf(`>${d.host}<`);
      expect(at, d.host).toBeGreaterThan(-1);
      expect(html.slice(at, at + 400)).toContain("topology only — never collected");
    }
  });
});
