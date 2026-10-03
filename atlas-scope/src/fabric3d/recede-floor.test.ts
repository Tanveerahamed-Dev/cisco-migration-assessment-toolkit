/**
 * recede-floor.test.ts — a RECEDED chassis keeps its state-indicator contrast (acceptance D4, WCAG
 * 1.4.11), in both themes, while still reading as receded.
 *
 * MEASURED before the fix (D4 re-grade refuter, release build, light, 1440x900, median chassis fill
 * against the ground beside it): the never-collected AP-floor3-01 was 4.30:1 with nothing selected
 * but 1.98:1 with core1 selected and 1.89:1 on an indeterminate path; wan-edge-rtr1.lab 5.44 -> 2.06;
 * collected chassis receded to 1.6-2.5:1 (dist2 4.42 -> 1.72). docs/render-decisions.md §9 had
 * raised the ghost fill to 3:1 with nothing selected only. Recession blended every receded fragment
 * toward the stage's HDR pre-image, so a subject anywhere on screen pulled the rest of the fabric
 * under the bar a state indicator needs.
 *
 * WHAT THIS PROVES, without a GPU: for every chassis-fill state class in the REAL compiled sample
 * (each collected device's body albedo x its own band tint, and the uncollected shell), in both
 * shipped palettes, a fragment at ANY lit level that clears 3:1 at full presence still clears
 * min(CHASSIS_RECEDED_FLOOR, its own contrast once the band hue has gone) at every recession depth
 * the scene uses, the hue's departure costing at most DESATURATION_COST — computed with the
 * uniforms the real patched shader is handed, and the shader's own
 * recession formula, which is pinned to the GLSL it mirrors. And recession still RECEDES: chroma
 * falls and a fragment above the floor loses contrast.
 *
 * WHAT IT DOES NOT PROVE: lighting, SSAO, the translucent shell's composite with what lies behind
 * it, and the deck the chassis actually stands on (the floor is held against the backdrop's worst
 * end, env.ts `stageGround`). Those are measured in the browser — docs/render-decisions.md §9.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { Color } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph } from "./scene";
import { profileFor } from "./quality";
import { CHASSIS_RECEDED_FLOOR, readTokens, type ThemeName } from "./materials";
import { RECEDE_DEPTH, RECEDE_NEIGHBOUR } from "./emphasis";
import { agxForward, stageGround } from "./env";

type Vec3 = [number, number, number];
const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

const W: Vec3 = [0.2126, 0.7152, 0.0722];
const lum = (c: Vec3): number => W[0] * c[0] + W[1] * c[1] + W[2] * c[2];
const contrast = (a: number, b: number): number => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
const shown = (pre: Vec3): number => lum(agxForward(pre));
/** Colourfulness independent of level: the band hue is what a receded chassis gives up. */
const saturation = (c: Vec3): number => (Math.max(...c) - Math.min(...c)) / Math.max(Math.max(...c), 1e-6);

/** The palette the app ships, declared on an element the way the cascade would for each theme. */
function shippedRoot(theme: ThemeName): HTMLElement {
  const css = readFileSync(resolve(__dirname, "../core/tokens.css"), "utf8");
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
  const host = document.createElement("div");
  const vars = { ...decls(rootBlock), ...(theme === "dark" ? decls(darkBlock) : {}) };
  for (const [k, v] of Object.entries(vars)) host.style.setProperty(k, v);
  document.body.appendChild(host);
  return host;
}

interface Uniforms {
  target: Vec3;
  mix: number;
  /** Absent before the floor existed; the formula below then has no guard, as the old shader had none. */
  inkDarker: boolean | undefined;
  fragment: string;
}

/** The uniforms and fragment source the REAL patched chassis material compiles with. */
function compiledUniforms(material: { onBeforeCompile: (s: never, r: never) => void }): Uniforms {
  const shader = {
    vertexShader: "#include <common>\n#include <begin_vertex>",
    fragmentShader:
      "#include <common>\n#include <color_fragment>\n#include <emissivemap_fragment>\n#include <opaque_fragment>\n#include <colorspace_fragment>",
    uniforms: {} as Record<string, { value: unknown }>,
  };
  material.onBeforeCompile(shader as never, undefined as never);
  const t = shader.uniforms.uRecedeTarget?.value as Color;
  const ink = shader.uniforms.uRecedeInkDarker?.value as number | undefined;
  return {
    target: [t.r, t.g, t.b],
    mix: shader.uniforms.uRecedeMix?.value as number,
    inkDarker: ink === undefined ? undefined : ink > 0.5,
    fragment: shader.fragmentShader,
  };
}

/**
 * What the band hue giving way may cost a fill in contrast, at most. Desaturation is the separate,
 * older channel of recession (EMPHASIS_FRAG_APPLY): AgX does not show a saturated colour and its
 * grey at the same linear luminance at quite the same level, so taking the hue away moves a fill a
 * little. MEASURED by the sweep below over every class in both palettes: at most 5.4 % (the light
 * stage's Critical red). A real chassis fill clears 4.1:1 at full presence (render-decisions.md §9),
 * so this cannot take one to the floor; it is bounded here so that it cannot grow unnoticed.
 */
const DESATURATION_COST = 0.06;

/**
 * The recession of one lit fragment, as the shader computes it: the albedo desaturated by r
 * (EMPHASIS_FRAG_APPLY, modelled on the lit colour), then the final radiance mixed toward the floor
 * target, unless it already lies on the ground side of that target, where it is left as lit
 * (EMPHASIS_FRAG_DIM).
 */
function desaturate(lit: Vec3, r: number): Vec3 {
  const y0 = lum(lit);
  return [y0 + (lit[0] - y0) * (1 - r), y0 + (lit[1] - y0) * (1 - r), y0 + (lit[2] - y0) * (1 - r)];
}
function recede(lit: Vec3, r: number, u: Uniforms): Vec3 {
  const desat = desaturate(lit, r);
  const t = r * u.mix;
  let out: Vec3 = [
    desat[0] + (u.target[0] - desat[0]) * t,
    desat[1] + (u.target[1] - desat[1]) * t,
    desat[2] + (u.target[2] - desat[2]) * t,
  ];
  if (u.inkDarker !== undefined && u.inkDarker === lum(desat) > lum(u.target)) out = desat;
  return out;
}

/** Every chassis-fill state class the sample renders, by its real albedo: collected bodies x their band tint, and the shell. */
function fillClasses(theme: ThemeName, root: HTMLElement): { classes: Map<string, Vec3>; uniforms: Uniforms } {
  const graph = buildFabricGraph({ devices, links, layout, theme, profile: profileFor("low"), tokenRoot: root });
  try {
    const classes = new Map<string, Vec3>();
    const body = graph.materials.body.color;
    const c = new Color();
    for (const s of graph.order) {
      if (s.ghost) continue;
      const mesh = s.group.body;
      expect(mesh, s.id).not.toBeNull();
      mesh!.getColorAt(s.slot, c);
      const albedo: Vec3 = [body.r * c.r, body.g * c.g, body.b * c.b];
      classes.set(`body ${albedo.map((v) => v.toFixed(4)).join(",")}`, albedo);
    }
    const g = graph.materials.ghost.color;
    classes.set("uncollected shell", [g.r, g.g, g.b]);
    return { classes, uniforms: compiledUniforms(graph.materials.body as never) };
  } finally {
    graph.dispose();
  }
}

describe("a receded chassis fill keeps its state-indicator contrast (D4)", () => {
  it("the floor is at least the WCAG 1.4.11 bar for a state indicator", () => {
    expect(CHASSIS_RECEDED_FLOOR).toBeGreaterThanOrEqual(3);
  });

  for (const theme of ["light", "dark"] as const) {
    const root = shippedRoot(theme);
    it(`${theme}: the shipped palette was parsed`, () => {
      expect(readTokens(theme, root).missing).toEqual([]);
    });

    it(`${theme}: every fill class, at every lit level that passes at full presence, holds min(floor, its own) at every recession depth, never louder`, () => {
      const { classes, uniforms } = fillClasses(theme, root);
      const ground = stageGround(readTokens(theme, root));
      // Guard the guard: both state classes the criterion names are present in the real sample.
      expect(classes.has("uncollected shell")).toBe(true);
      expect(classes.size).toBeGreaterThanOrEqual(3);
      const failures: string[] = [];
      let checked = 0;
      for (const [name, albedo] of classes) {
        // A sweep of irradiance, not a guessed lighting model: whatever the lights make of this albedo.
        for (let e = 0.05; e <= 40; e *= 1.15) {
          const lit: Vec3 = [albedo[0] * e, albedo[1] * e, albedo[2] * e];
          const full = contrast(shown(lit), ground.y);
          // Only fragments drawn on the INK side of the ground and passing at full presence are
          // state indicators the floor protects; the rest are measured at full presence (fabric).
          const inkSide = ground.inkDarker ? shown(lit) < ground.y : shown(lit) > ground.y;
          if (!inkSide || full < 3) continue;
          for (const r of [RECEDE_NEIGHBOUR, RECEDE_DEPTH, 1]) {
            checked += 1;
            const got = contrast(shown(recede(lit, r, uniforms)), ground.y);
            // The dim never takes a fill under the floor, nor under where the hue's departure left it...
            const greyed = contrast(shown(desaturate(lit, r)), ground.y);
            const need = Math.min(CHASSIS_RECEDED_FLOOR, greyed);
            if (got < need - 0.01) failures.push(`${name} e=${e.toFixed(2)} r=${r}: ${full.toFixed(2)}:1 -> ${got.toFixed(2)}:1 (needs ${need.toFixed(2)})`);
            // ...never makes it LOUDER than the hue's departure left it (a receded chassis is context)...
            if (got > greyed + 0.01) failures.push(`${name} e=${e.toFixed(2)} r=${r}: louder when receded, ${greyed.toFixed(2)}:1 -> ${got.toFixed(2)}:1`);
            // ...and the hue's departure is itself bounded.
            if (greyed < full * (1 - DESATURATION_COST)) failures.push(`${name} e=${e.toFixed(2)} r=${r}: desaturation alone ${full.toFixed(2)}:1 -> ${greyed.toFixed(2)}:1`);
          }
        }
      }
      expect(checked).toBeGreaterThan(100);
      expect(failures.slice(0, 12)).toEqual([]);
    });

    it(`${theme}: recession still recedes — the band hue goes, and a fill above the floor loses contrast`, () => {
      const { classes, uniforms } = fillClasses(theme, root);
      const ground = stageGround(readTokens(theme, root));
      let receded = 0;
      for (const [name, albedo] of classes) {
        for (let e = 0.05; e <= 40; e *= 1.15) {
          const lit: Vec3 = [albedo[0] * e, albedo[1] * e, albedo[2] * e];
          const full = contrast(shown(lit), ground.y);
          const inkSide = ground.inkDarker ? shown(lit) < ground.y : shown(lit) > ground.y;
          if (!inkSide || full < CHASSIS_RECEDED_FLOOR + 0.4) continue;
          const back = recede(lit, RECEDE_DEPTH, uniforms);
          const got = contrast(shown(back), ground.y);
          expect(got, `${name} e=${e.toFixed(2)}: receded ${got.toFixed(2)} vs full ${full.toFixed(2)}`).toBeLessThan(full - 0.15);
          // The hue goes: at the depth a non-subject recedes to, under two thirds of it is left.
          if (saturation(lit) > 0.1) expect(saturation(back), name).toBeLessThan((saturation(lit) * 2) / 3);
          receded += 1;
        }
      }
      expect(receded).toBeGreaterThan(20);
    });
  }

  it("the formula above is the shader's: the compiled fragment carries exactly this recession", () => {
    const { uniforms } = fillClasses("light", shippedRoot("light"));
    const src = uniforms.fragment.replace(/\s+/g, " ");
    expect(src).toContain("diffuseColor.rgb = mix(diffuseColor.rgb, vec3(lum), r);");
    // Recession is colour, never alpha: a thinned translucent shell composites with the ground behind it.
    expect(src).not.toMatch(/diffuseColor\.a \*=/);
    expect(src).toContain("vec3 _rec = mix(_lit, uRecedeTarget, clamp(vRecede, 0.0, 1.0) * uRecedeMix);");
    expect(src).toContain("if ((uRecedeInkDarker > 0.5) == (_yl > dot(uRecedeTarget, _w))) _rec = _lit;");
  });
});
