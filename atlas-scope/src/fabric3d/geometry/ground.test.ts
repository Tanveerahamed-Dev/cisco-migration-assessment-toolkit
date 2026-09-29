/**
 * ground.test.ts — the contact decal, which is the only grounding cue in this scene that works on
 * every quality tier, and which shipped doing nothing at all.
 *
 * WHAT THESE TESTS PROVE
 *   - The decal's full-strength plateau ends INSIDE the chassis silhouette, on both axes. This is
 *     the exact relationship that broke: `CONTACT_SPREAD` (geometry) and `CONTACT_PLATEAU`
 *     (materials) were implicitly coupled, lived in different files, and drifted apart, so the
 *     decal's strongest region sat entirely underneath the chassis standing on it and only its
 *     weakest tail was ever visible.
 *   - The alpha the decal actually carries where a chassis meets its deck is a contact shadow and
 *     not a rounding error. The shipped profile delivered 0.166 there before opacity; anything in
 *     that region is invisible on a near-black deck.
 *   - The failure is reachable by the test. `contactDecalGrounds` is fed a deliberately wrong
 *     plateau and has to say so — a predicate only ever called with passing arguments is not a
 *     guard.
 *
 * WHAT THEY DO NOT PROVE
 *   - That the render is grounded. That is a pixel question and it was answered with pixels: a
 *     horizontal luminance scan across the deck either side of a focused chassis, real GPU, tier
 *     `high`, dark theme, went from 99 98 [chassis] 96 94 with no decal to 98 91 [chassis] 73 63
 *     with it. The numbers are in docs/render-decisions.md §5.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../../core/data";
import { describeGolden } from "../../test-support/golden-sample";
import { CONTACT_PLATEAU } from "../materials";
import { computeLayout } from "../layout";
import {
  CONTACT_SILHOUETTE_RADIUS,
  CONTACT_SPREAD,
  MIN_SURFACE_UNDER_NODE,
  contactDecalGrounds,
  deckFadeAlpha,
  deckSupport,
  surfaceUnderNodes,
} from "./ground";

/**
 * The decal's alpha at a given normalised radius, mirroring the texture generator in materials.ts.
 * Duplicated deliberately: a test that imported the generator's own arithmetic would agree with it
 * whatever it said.
 */
function decalAlpha(r: number, plateau = CONTACT_PLATEAU): number {
  const t = Math.max(0, Math.min(1, (1 - r) / (1 - plateau)));
  return t * t * (3 - 2 * t);
}

describe("the contact decal's plateau and the chassis silhouette", () => {
  it("puts the silhouette outside the plateau on both axes", () => {
    // If this fails the decal is invisible under its own caster, whatever it looks like in code.
    expect(CONTACT_PLATEAU).toBeLessThan(CONTACT_SILHOUETTE_RADIUS[0]);
    expect(CONTACT_PLATEAU).toBeLessThan(CONTACT_SILHOUETTE_RADIUS[1]);
    expect(contactDecalGrounds()).toBe(true);
  });

  it("reports FALSE when the plateau is pulled inside the silhouette", () => {
    // The shipped radial fade peaked at the centre, which is this case taken to its limit.
    expect(contactDecalGrounds(0.9)).toBe(false);
    expect(contactDecalGrounds(CONTACT_SILHOUETTE_RADIUS[1])).toBe(false);
  });

  it("still carries most of its alpha where the chassis meets the deck", () => {
    for (const r of CONTACT_SILHOUETTE_RADIUS) {
      // 0.8 is well clear of the 0.166 the radial fade delivered there, and well clear of the
      // region where a 0.7 opacity stops reading as contact on a near-black deck.
      expect(decalAlpha(r)).toBeGreaterThan(0.8);
    }
  });

  it("reaches zero before the decal's own edge, so it never ends on a visible ellipse", () => {
    expect(decalAlpha(1)).toBe(0);
    expect(decalAlpha(0.97)).toBeLessThan(0.02);
  });

  it("keeps the two constants describing the same decal", () => {
    // CONTACT_SILHOUETTE_RADIUS is derived from CONTACT_SPREAD; if someone edits one by hand this
    // is what notices.
    expect(CONTACT_SILHOUETTE_RADIUS[0]).toBeCloseTo(2 / CONTACT_SPREAD[0], 10);
    expect(CONTACT_SILHOUETTE_RADIUS[1]).toBeCloseTo(2 / CONTACT_SPREAD[1], 10);
    // A decal narrower than the chassis cannot show a contact shadow at all.
    expect(CONTACT_SPREAD[0]).toBeGreaterThan(2);
    expect(CONTACT_SPREAD[1]).toBeGreaterThan(2);
  });
});

/* ── every NODE stands on a surface (render audit #5) ─────────────────────────────────────────
   The tier decks fade radially from their tier's centre, so a node at the extreme of a wide or
   sparse tier stood on pure backdrop: `wan-edge-rtr1.lab` and `AP-floor3-01` rendered floating at
   both quality tiers, and a darkening contact decal cannot ground anything on a surface that is
   already the backdrop. The doctrine is per node; this asserts it per node, on the REAL layout. */

describe("the surface under every laid-out node", () => {
  const layout = computeLayout({ devices: fabric.devices, links: fabric.links, tiers: fabric.tiers });

  it("mirrors the deck's radial fade texture", () => {
    expect(deckFadeAlpha(0)).toBe(1);
    expect(deckFadeAlpha(1)).toBe(0);
    expect(deckFadeAlpha(1.4)).toBe(0);
    expect(deckFadeAlpha(0.5)).toBeCloseTo(Math.pow(0.5, 2.2), 10);
  });

  it("finds the nodes the tier deck alone leaves floating — the guard is not inert here", () => {
    /* RE-EXPRESSED 2026-09-29 (P3C-V2-3): the floating node used to be typed (wan-edge-rtr1.lab), which exists only
       in the sample. The reading must DISCRIMINATE on any fabric: it measures every node, some node reads as
       supported by the deck, and every node it reads as floating is one the pads then carry (asserted for all
       nodes below). That the sample has a floating node at all — so the pads are not inert there — is pinned by
       name in the golden block. */
    const deckOnly = deckSupport(layout.tierBounds, layout.nodes);
    expect(deckOnly.size).toBe(layout.nodes.length);
    expect([...deckOnly.values()].some((a) => a >= MIN_SURFACE_UNDER_NODE)).toBe(true);
    const floating = [...deckOnly].filter(([, a]) => a < MIN_SURFACE_UNDER_NODE).map(([id]) => id);
    const surface = surfaceUnderNodes(layout.tierBounds, layout.nodes);
    for (const id of floating) expect(surface.get(id) ?? 0, `${id} floats on the deck and must get a pad`).toBeGreaterThanOrEqual(MIN_SURFACE_UNDER_NODE);
  });

  it("puts a surface under every node once pads are laid", () => {
    const surface = surfaceUnderNodes(layout.tierBounds, layout.nodes);
    expect(surface.size).toBe(layout.nodes.length);
    const floating = [...surface].filter(([, a]) => a < MIN_SURFACE_UNDER_NODE).map(([id]) => id);
    expect(floating).toEqual([]);
  });
});

describeGolden("the surface under the reference sample's nodes", () => {
  it("wan-edge-rtr1.lab floats on the tier deck alone, so the pads are not inert on the sample", () => {
    const layout = computeLayout({ devices: fabric.devices, links: fabric.links, tiers: fabric.tiers });
    expect(deckSupport(layout.tierBounds, layout.nodes).get("wan-edge-rtr1.lab")).toBeLessThan(MIN_SURFACE_UNDER_NODE);
  });
});
