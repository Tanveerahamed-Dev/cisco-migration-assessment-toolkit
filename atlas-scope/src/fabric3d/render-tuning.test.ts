/**
 * render-tuning.test.ts — the per-theme material relationships the 2026-09-21 render repair rests on.
 *
 * WHAT THESE TESTS PROVE
 *   - The light-theme chassis body is light enough for the band tint (a MULTIPLY on the albedo) to
 *     carry hue: at the old 0.8 step every light chassis rendered the same charcoal.
 *   - The light-theme floor is stepped off the stage only as far as the albedo ceiling forces and is
 *     faded right back, so its radial fade cannot paint a dark disc under the empty fabric middle.
 *   - The dark-theme ground planes have their direct specular cut, which was the pale glow under
 *     every node, and their deck lift is small.
 *   - The contact decal is strong enough in both themes to darken a chassis base visibly.
 *   - Recession targets the STAGE (so light-theme recession lifts toward white instead of darkening
 *     a chassis into more contrast).
 *
 * WHAT THEY DO NOT PROVE
 *   - Pixels. The render evidence is the GPU capture measurements quoted in materials.ts and
 *     scene.ts next to each constant. These tests stop the relationships from silently drifting.
 */
import { describe, expect, it } from "vitest";
import { Color, MeshBasicMaterial, MeshPhysicalMaterial, MeshStandardMaterial } from "three";
import {
  DARK_GROUND_SPECULAR,
  LIGHT_BODY_STEP,
  LIGHT_CONTACT_OPACITY,
  LIGHT_FLOOR_OPACITY,
  RECEDE_MIX,
  readTokens,
  retintMaterials,
  type MaterialLibrary,
} from "./materials";

function bareLibrary(): MaterialLibrary {
  const lib = {
    body: new MeshStandardMaterial(),
    bezel: new MeshPhysicalMaterial(),
    dark: new MeshStandardMaterial(),
    rail: new MeshStandardMaterial(),
    led: new MeshStandardMaterial(),
    ghost: new MeshStandardMaterial(),
    hatch: new MeshBasicMaterial(),
    deck: new MeshPhysicalMaterial(),
    ground: new MeshPhysicalMaterial(),
    contact: new MeshBasicMaterial(),
    halo: new MeshBasicMaterial(),
    hoverShell: new MeshBasicMaterial(),
    stateRim: new MeshStandardMaterial(),
  } as unknown as MaterialLibrary;
  lib.all = () =>
    [lib.body, lib.bezel, lib.dark, lib.rail, lib.led, lib.ghost, lib.hatch, lib.deck, lib.ground, lib.contact, lib.halo, lib.hoverShell, lib.stateRim];
  lib.dispose = () => {};
  return lib;
}

const lum = (c: Color): number => 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;

describe("per-theme render tuning", () => {
  it("light chassis body is mid-grey, not charcoal, so the band tint has a diffuse term to ride on", () => {
    const lib = bareLibrary();
    retintMaterials(lib, readTokens("light"));
    expect(LIGHT_BODY_STEP).toBeLessThanOrEqual(0.55);
    // Linear luminance. The old 0.8 step gave ~0.18; the tint was lost under neutral specular.
    expect(lum(lib.body.color)).toBeGreaterThan(0.3);
  });

  it("light floor stays near the stage and is faded back (no shadow of nothing)", () => {
    const lib = bareLibrary();
    const t = readTokens("light");
    retintMaterials(lib, t);
    // Stepped only as far as the dielectric albedo ceiling forces (0.12), and faded right back.
    expect(lum(lib.ground.color)).toBeGreaterThanOrEqual(lum(t.color("--stage-bg")) * 0.85);
    expect(lib.ground.opacity).toBe(LIGHT_FLOOR_OPACITY);
    expect(LIGHT_FLOOR_OPACITY).toBeLessThanOrEqual(0.25);
  });

  it("dark ground planes carry a cut specular and a small lift (the glow under every node)", () => {
    const lib = bareLibrary();
    const t = readTokens("dark");
    retintMaterials(lib, t);
    expect(lib.deck.specularIntensity).toBe(DARK_GROUND_SPECULAR);
    expect(lib.ground.specularIntensity).toBe(DARK_GROUND_SPECULAR);
    expect(DARK_GROUND_SPECULAR).toBeLessThanOrEqual(0.2);
    // The deck stays within a hair of the stage: the chassis rests on a surface, not a spotlight.
    expect(lum(lib.deck.color) - lum(t.color("--stage-bg"))).toBeLessThan(0.02);
  });

  it("the contact decal is strong enough to darken a chassis base in both themes", () => {
    const light = bareLibrary();
    retintMaterials(light, readTokens("light"));
    expect(light.contact.opacity).toBe(LIGHT_CONTACT_OPACITY);
    expect(LIGHT_CONTACT_OPACITY).toBeGreaterThanOrEqual(0.55);
    const dark = bareLibrary();
    retintMaterials(dark, readTokens("dark"));
    expect(dark.contact.opacity).toBeGreaterThanOrEqual(0.6);
  });

  it("recession blends toward its floor target and never all the way", () => {
    /* Both stages now recede toward a target AT the receded-chassis contrast floor (materials.ts
       chassisRecedeTarget), so the blend means the same on both; the old light < dark ordering
       existed only because the light target was an HDR pre-image several times brighter than any
       chassis. Substantial (> 0.5) so recession reads; < 1 so a receded chassis keeps its shading. */
    for (const theme of ["dark", "light"] as const) {
      expect(RECEDE_MIX[theme]).toBeLessThan(1);
      expect(RECEDE_MIX[theme]).toBeGreaterThan(0.5);
    }
  });
});
