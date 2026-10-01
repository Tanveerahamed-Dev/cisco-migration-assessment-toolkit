/**
 * emphasis.mirrors.test.ts — everything the emphasis patch can dim actually receives a value.
 *
 * MEASURED (C5 audit): with one device selected, the other chassis desaturated but their state
 * rings stayed fully saturated, so the brightest things on screen were NON-selected rings. The ring
 * material was emphasis-patched; the ring meshes never carried the recession attribute, so the
 * patch read zero. The role glyphs had the same gap. The guard here is the CLASS, not the two
 * names: every instanced mesh in the real scene graph whose material is emphasis-patched must carry
 * `aRecede`, and stepping the emphasis must write the device's own value into it.
 */
import { describe, expect, it } from "vitest";
import { InstancedBufferAttribute, InstancedMesh, type Material } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph } from "./scene";
import { profileFor } from "./quality";
import { RECEDE_ATTRIBUTE } from "./materials";
import { createEmphasisState, stepEmphasis } from "./emphasis";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

const patched = (m: Material | Material[]): boolean =>
  (Array.isArray(m) ? m : [m]).some((x) => x.customProgramCacheKey().startsWith("atlas-emphasis"));

describe("emphasis reaches every patched instanced mesh", () => {
  for (const tier of ["low", "high"] as const) {
    it(`${tier}: every emphasis-patched InstancedMesh carries ${RECEDE_ATTRIBUTE}`, () => {
      const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor(tier) });
      const missing: string[] = [];
      let checked = 0;
      graph.scene.traverse((o) => {
        if (!(o instanceof InstancedMesh) || !patched(o.material)) return;
        checked += 1;
        if (o.geometry.getAttribute(RECEDE_ATTRIBUTE) === undefined) missing.push(o.name || o.type);
      });
      expect(checked).toBeGreaterThan(5);
      expect(missing).toEqual([]);
    });
  }

  it("a receded device's state ring and role glyph receive the device's own recession", () => {
    const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("low") });
    const state = createEmphasisState(graph.order.length);
    const subject = graph.order[0];
    expect(subject).toBeDefined();
    for (const s of graph.order) state.target[s.index] = s === subject ? 0 : 0.62;
    state.dirty = true;
    for (let i = 0; i < 40; i += 1) stepEmphasis(graph, state, 50);
    expect(graph.mirrors.length).toBeGreaterThanOrEqual(graph.stateRings.length + graph.roleGlyphs.length);
    for (const mirror of graph.mirrors) {
      const attr = mirror.attr as InstancedBufferAttribute;
      mirror.deviceIndex.forEach((deviceIndex, i) => {
        expect(attr.getX(i)).toBeCloseTo(state.current[deviceIndex] ?? -1, 5);
      });
    }
    // And the non-subject rings are genuinely receded, not left at 0.
    const ringValues = graph.mirrors.flatMap((m) => Array.from(m.attr.array as Float32Array));
    expect(Math.max(...ringValues)).toBeGreaterThan(0.5);
  });
});
