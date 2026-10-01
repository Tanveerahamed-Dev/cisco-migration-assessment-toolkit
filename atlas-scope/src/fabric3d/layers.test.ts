/**
 * layers.test.ts — the render-layer namespace, and the three budget/contract numbers next to it.
 *
 * WHAT THESE TESTS PROVE
 *   - `assertLayerRegistry` reports a collision, an out-of-range layer, and an effect that reports
 *     a layer other than the one it was pinned to.
 *   - postprocessing really does allocate Selection layers from a module-global counter that never
 *     resets, and the values it hands out reach PICK_LAYER — i.e. the collision that painted every
 *     chassis with the blocked-outline's red is reachable by construction, not hypothetical.
 *   - postfx.ts pins all three selections and reads them back.
 *   - The draw-call ceiling in the code is the number design-brief.md publishes, read out of the
 *     brief at test time rather than copied into this file — and so are the two numbers the
 *     ceiling is DERIVED from, so the published table cannot drift from the model.
 *   - The shadow filter is named once and is a filter the pinned three version still implements.
 *
 * WHAT THEY DO NOT PROVE
 *   - Nothing here renders. Whether the pinned layers keep the outline mask empty is a pixel
 *     question, answered by capture: the measured evidence is that the red fraction around every
 *     device dropped from 0.147 to 0.010 (the value a clean frame already showed) once the pin
 *     landed.
 *   - The ceiling is checked for AGREEMENT with the brief here. Whether a real frame stays under it
 *     is measured in the browser, and the measurement has to name the STATE it was taken in: an
 *     earlier version of this line said "74 calls at `high`, 2026-09-21" as though that described
 *     a frame, when it was taken with nothing selected and no trace. The full 2026-09-21 sweep
 *     (ANGLE → Intel D3D11, 1920×1080, `high`, converged, 30 rAF samples, min === max per row) is
 *     74 idle / 103 with one outline effect active / 141 with both — and 141 against a flat 120
 *     was a standing, invisible breach for the whole of the path-trace surface. The model that
 *     replaced it is asserted below.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PCFShadowMap, PCFSoftShadowMap } from "three";
import { Selection } from "postprocessing";
import { LAYER_REGISTRY, PICK_LAYER, SELECTION_LAYERS, assertLayerRegistry } from "./layers";
import {
  DRAW_CALL_BUDGET,
  DRAW_CALL_BUDGET_BASE,
  DRAW_CALL_BUDGET_PER_OUTLINE,
  INTENDED_SHADOW_MAP_TYPE,
  OUTLINE_EFFECT_COUNT,
  drawCallBudgetFor,
} from "./scene";

const source = (file: string): string => readFileSync(resolve(__dirname, file), "utf8");

/** Source with comments stripped — a rule about CODE must not be satisfied or broken by prose. */
const code = (file: string): string =>
  source(file)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

describe("the render-layer registry", () => {
  it("is collision-free as declared", () => {
    expect(assertLayerRegistry()).toEqual([]);
  });

  it("keeps the hit-test layer out of the post chain's range", () => {
    const selectionLayers = Object.values(SELECTION_LAYERS);
    expect(selectionLayers).not.toContain(PICK_LAYER);
    expect(new Set(selectionLayers).size).toBe(selectionLayers.length);
    for (const layer of selectionLayers) {
      expect(layer).toBeGreaterThan(PICK_LAYER);
      expect(layer).toBeLessThanOrEqual(31);
    }
  });

  it("names both owners when two things claim one layer", () => {
    const violations = assertLayerRegistry([["bloom", PICK_LAYER]]);
    expect(violations).toHaveLength(1);
    expect(violations[0]).toContain("bloom");
    expect(violations[0]).toContain("pick");
  });

  it("catches an effect that did not take the layer it was pinned to", () => {
    // The pin is an instruction to a library we do not control. This is the read-back.
    const violations = assertLayerRegistry([["blockedOutline", 4]]);
    expect(violations).toHaveLength(1);
    expect(violations[0]).toContain("reports layer 4");
    expect(violations[0]).toContain(String(SELECTION_LAYERS.blockedOutline));
  });

  it("accepts an effect reporting exactly what it was pinned to", () => {
    expect(
      assertLayerRegistry([
        ["bloom", SELECTION_LAYERS.bloom],
        ["selectionOutline", SELECTION_LAYERS.selectionOutline],
        ["blockedOutline", SELECTION_LAYERS.blockedOutline],
      ]),
    ).toEqual([]);
  });

  it("rejects a layer outside the usable range", () => {
    const registryCopy = [...LAYER_REGISTRY];
    expect(registryCopy.length).toBeGreaterThan(0);
    expect(assertLayerRegistry([["bloom", 32]])).not.toEqual([]);
  });
});

describe("why the pin exists: postprocessing allocates layers from a global counter", () => {
  it("hands every new Selection the next layer, and never resets", () => {
    // This is the live library, not a model of it. Two consecutive allocations are consecutive
    // integers, so the layer an effect gets is a function of how many effects the PAGE has built —
    // which is why the second post chain in a StrictMode page landed on 5, 6, 7 and 7 is
    // PICK_LAYER. Only relative behaviour is asserted: the absolute value depends on what else in
    // this worker has constructed an effect.
    const first = new Selection();
    const second = new Selection();
    const third = new Selection();
    expect(second.layer).toBe(first.layer + 1);
    expect(third.layer).toBe(first.layer + 2);
    // ...and the counter starts low enough to reach the hit-test layer within a few chains.
    expect(first.layer).toBeLessThanOrEqual(PICK_LAYER + 3 * 8);
  });

  it("moves a selection's members when the layer is reassigned, so pinning an empty set is safe", () => {
    const sel = new Selection();
    const pinned = SELECTION_LAYERS.blockedOutline;
    sel.layer = pinned;
    expect(sel.layer).toBe(pinned);
    expect(sel.size).toBe(0);
  });
});

describe("postfx pins what it constructs", () => {
  const postfx = source("postfx.ts");

  it("assigns every selection layer from the registry", () => {
    expect(postfx).toContain("bloom.selection.layer = SELECTION_LAYERS.bloom");
    expect(postfx).toContain("selectionOutline.selection.layer = SELECTION_LAYERS.selectionOutline");
    expect(postfx).toContain("blockedOutline.selection.layer = SELECTION_LAYERS.blockedOutline");
  });

  it("reads the layers back rather than trusting the assignment", () => {
    expect(postfx).toContain("assertLayerRegistry([");
    expect(postfx).toContain("bloom.selection.layer");
  });

  it("does not use the world-unit SSAO cutoffs that zeroed the pass", () => {
    // worldDistanceThreshold / worldProximityThreshold map a WORLD distance through
    // viewZToOrthographicDepth(camera.near, camera.far). With this scene's near 135 / far 608.5 the
    // published values resolved to a distance cutoff the fabric sat behind and a proximity cutoff
    // clamped to zero, so no sample could occlude anything: SSAO rendered every frame and changed
    // no pixel. The normalised thresholds below it are what the shader actually compares against.
    expect(postfx).not.toMatch(/worldDistanceThreshold:/);
    expect(postfx).not.toMatch(/worldProximityThreshold:/);
    expect(postfx).toContain("rangeThreshold: AO_PROXIMITY_WORLD / depthSpan");
  });

  it("seeds the SSAO noise deterministically, so one scene's capture equals another's", () => {
    expect(postfx).toContain("deterministicSsaoNoise()");
    expect(code("postfx.ts")).not.toContain("Math.random");
  });
});

describe("the two published numbers this file owns", () => {
  it("implements the draw-call ceiling design-brief.md publishes", () => {
    const brief = readFileSync(resolve(__dirname, "../../docs/design-brief.md"), "utf8");
    const stated = brief.match(/Draw-call ceiling for the entire scene:\s*\*\*(\d+)\*\*/);
    expect(stated, "design-brief.md no longer states a draw-call ceiling in the expected form")
      .not.toBeNull();
    expect(DRAW_CALL_BUDGET).toBe(Number(stated?.[1]));
  });

  it("publishes the two numbers the ceiling is derived from, not just the total", () => {
    /* The ceiling used to be a bare constant, and a bare constant cannot say WHICH frame it
       describes. It described the idle one, so every frame with a path trace on screen breached it
       permanently and the only report was a DEV-only console line absent from the shipped bundle.
       The ceiling is now base + outlineEffects × surcharge; a reader has to be able to check that
       arithmetic against the brief, so all three numbers are published and all three are asserted. */
    const brief = readFileSync(resolve(__dirname, "../../docs/design-brief.md"), "utf8");
    const base = brief.match(/Base — no outline effect active \|[^|]*\|\s*\*\*(\d+)\*\*/);
    const per = brief.match(/Each outline effect with a non-empty selection \|[^|]*\|\s*\*\*\+(\d+)\*\*/);
    expect(base, "design-brief.md §4.4 no longer publishes the base draw-call budget").not.toBeNull();
    expect(per, "design-brief.md §4.4 no longer publishes the per-outline surcharge").not.toBeNull();
    expect(DRAW_CALL_BUDGET_BASE).toBe(Number(base?.[1]));
    expect(DRAW_CALL_BUDGET_PER_OUTLINE).toBe(Number(per?.[1]));
    expect(DRAW_CALL_BUDGET).toBe(DRAW_CALL_BUDGET_BASE + OUTLINE_EFFECT_COUNT * DRAW_CALL_BUDGET_PER_OUTLINE);
  });

  it("budgets every outline effect the post chain can actually run at once", () => {
    /* OUTLINE_EFFECT_COUNT is what turns the per-frame surcharge into the published ceiling. If a
       third OutlineEffect is ever added to postfx.ts, the ceiling must move with it — otherwise the
       new one is free, which is precisely how the second one became free. Counted from the source
       with comments stripped, so a mention in prose cannot satisfy or break it. */
    const postfx = code("postfx.ts");
    const constructed = postfx.match(/new OutlineEffect\(/g) ?? [];
    expect(constructed.length).toBe(OUTLINE_EFFECT_COUNT);
  });

  it("applies a budget that grows with the outline effects actually active", () => {
    // The model itself, not a re-derivation of it: 0 active outlines is the tightest frame.
    expect(drawCallBudgetFor(0)).toBe(DRAW_CALL_BUDGET_BASE);
    expect(drawCallBudgetFor(1)).toBe(DRAW_CALL_BUDGET_BASE + DRAW_CALL_BUDGET_PER_OUTLINE);
    expect(drawCallBudgetFor(OUTLINE_EFFECT_COUNT)).toBe(DRAW_CALL_BUDGET);
    // Clamped at both ends: a miscounted caller must not be able to buy unlimited headroom.
    expect(drawCallBudgetFor(-3)).toBe(DRAW_CALL_BUDGET_BASE);
    expect(drawCallBudgetFor(99)).toBe(DRAW_CALL_BUDGET);
  });

  it("covers the frames measured in the browser, and is not slack around them", () => {
    /* The measurements this budget was derived from (2026-09-21, ANGLE → Intel D3D11, 1920×1080,
       `high`, converged, 30 rAF samples per row, min === max). Every row must FIT, and no row may
       have more than 40% headroom — a budget nothing can trip is the defect this replaced, in the
       opposite direction. */
    const measured: [outlines: number, calls: number][] = [
      [0, 74], // nothing selected, no trace
      [1, 103], // device selected; also a DELIVERED trace, which measures identically
      [2, 141], // denied or indeterminate trace — the ceiling of the design
    ];
    for (const [outlines, calls] of measured) {
      const budget = drawCallBudgetFor(outlines);
      expect(calls, `${outlines} outline(s): ${calls} calls must fit in ${budget}`)
        .toBeLessThanOrEqual(budget);
      expect(budget, `${outlines} outline(s): ${budget} is more than 40% above the measured ${calls}`)
        .toBeLessThanOrEqual(Math.round(calls * 1.4));
    }
  });

  it("the budget check reads the per-frame ceiling, not the published total", () => {
    /* A source assertion, and it is the one that matters: the constant could be perfect while the
       render loop still compared against the flat ceiling. Comments stripped so the prose above
       cannot satisfy it. */
    const scene = code("scene.ts");
    // Budgeted on the outline passes that RUN this frame (a deselect, or a rebuilt chain, runs one
    // with an empty selection), never on fewer than the live selections.
    expect(scene).toContain("frameDrawCallBudget = drawCallBudgetFor(Math.max(activeOutlines(), outlinesThisFrame))");
    expect(scene).toContain("const outlinesThisFrame = post.outlinesUpdatingNextRender();");
    expect(scene).toContain("renderer.info.render.calls > frameDrawCallBudget");
    expect(scene).not.toMatch(/renderer\.info\.render\.calls\s*>\s*DRAW_CALL_BUDGET\b/);
  });

  it("intends a shadow filter the pinned three version still implements", () => {
    // PCFSoftShadowMap is still EXPORTED by three 0.186.0 and is rejected at use:
    // "THREE.WebGLShadowMap: PCFSoftShadowMap has been removed. Using PCFShadowMap instead."
    // Naming it would be asking for a filter that cannot be granted, which is how the brief's soft
    // shadows were silently not in force.
    expect(INTENDED_SHADOW_MAP_TYPE).toBe(PCFShadowMap);
    expect(INTENDED_SHADOW_MAP_TYPE).not.toBe(PCFSoftShadowMap);
  });

  it("asserts the shadow type after assigning it", () => {
    const scene = source("scene.ts");
    expect(scene).toContain("renderer.shadowMap.type = INTENDED_SHADOW_MAP_TYPE");
    expect(scene).toContain("renderer.shadowMap.type !== INTENDED_SHADOW_MAP_TYPE");
  });
});
