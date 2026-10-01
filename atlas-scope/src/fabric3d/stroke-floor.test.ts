/**
 * stroke-floor.test.ts — acceptance C5 item 8 ("1px hairline links"), guarded as a CLASS.
 *
 * THE DEFECT (acceptance report at 70bea72, C5): "a 1-device-px dashed stroke about 450 device px
 * long in the core2→access9/access3 bundle, identical at dark/high and dark/low" — 0.5 CSS px at
 * DSF 2, against design-brief §4.5's "Minimum painted stroke is 2 CSS px". The grader could not name
 * the object. IDENTIFIED (2026-09-24, a debug copy of the app with the three.js graph exposed, the
 * overview at 1440x900 DSF 2, dark): hiding the batch `cables:solid|2|1|2x3` — bridges of unobserved
 * speed, drawn as two 2 px rails with a 3 px gap — removed the stroke; setting that batch's
 * `depthWrite` to false alone turned it back into full-width rails. It was NOT a thin stroke anybody
 * asked for. It was a 2 CSS px rail of one bridge, sliced down to one device pixel by the DEPTH of
 * its neighbour's INVISIBLE fragments: a LineMaterial quad covers its rail gaps and its anti-alias
 * margin, those fragments carry zero (or partial) coverage, and with `depthWrite: true` they still
 * stamp the depth buffer, so a parallel cable in the same bundle drawn later and a hair farther away
 * failed the depth test everywhere its neighbour's quad lay. Which one is nearer flips segment by
 * segment, which is why the survivor read as a DASHED line. The same mechanism the deck planes had
 * (materials.ts, "A depth write is not alpha-weighted").
 *
 * So the class is not "the one bundle" and not "one batch's width". It is every screen-space stroke
 * the fabric draws, and two properties of each:
 *   1. its painted width per rail is at least MIN_STROKE_PX (2 CSS px), read from the program the GPU
 *      actually compiles, not from the caller's request;
 *   2. it cannot occlude anything with fragments it does not paint — `depthWrite` is off.
 * The enumeration is structural, not a list of names: every Line* material reachable from the scene
 * graph the app builds (every theme, every tier) plus the trace overlay, and a source check that no
 * other stroke-material constructor exists in the fabric to escape it. The DOM half of "the fabric
 * paints" — the label leader lines drawn over the stage — is held to the same floor.
 *
 * WHAT THIS DOES NOT PROVE: pixels. jsdom has no WebGL. The DSF-2 pixel probe
 * (review/probe-fabric.mjs --hairline) is the rendered evidence.
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Material, Object3D } from "three";
import type { LineMaterial } from "three/addons/lines/LineMaterial.js";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph } from "./scene";
import { createFlowOverlay } from "./flow";
import { createCableMaterial, MIN_STROKE_PX } from "./geometry/cables";
import { readTokens } from "./materials";
import { profileFor } from "./quality";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

/** Every material of every object under `root`. */
function materialsUnder(root: Object3D): { owner: string; material: Material }[] {
  const out: { owner: string; material: Material }[] = [];
  root.traverse((o) => {
    const m = (o as Object3D & { material?: Material | Material[] }).material;
    if (m === undefined) return;
    for (const one of Array.isArray(m) ? m : [m]) out.push({ owner: o.name || o.type, material: one });
  });
  return out;
}

const isStroke = (m: Material): boolean => /Line/.test(m.type);

/**
 * The width, in CSS pixels, that ONE rail of this stroke paints — read off the compiled fragment
 * program and the quad width, which is what the GPU draws. `linewidth` is the quad (encoded width
 * plus the anti-alias margin); the program's `_u` term names where the encoded edge sits in it; a
 * multi-rail program names its rail width in the `_loc < railPx` cut.
 */
function paintedRailPx(m: LineMaterial): number {
  const edge = /abs\( vUv\.x \) \/ ([\d.]+)/.exec(m.fragmentShader);
  if (edge === null) throw new Error(`${m.type}: no edge term in the program — not a fabric stroke`);
  const nominal = m.linewidth * Number(edge[1]);
  const rail = /_loc < ([\d.]+) \?/.exec(m.fragmentShader);
  return rail === null ? nominal : Math.min(nominal, Number(rail[1]));
}

function everyStrokeTheAppBuilds(): { owner: string; material: Material }[] {
  const out: { owner: string; material: Material }[] = [];
  for (const theme of ["dark", "light"] as const) {
    for (const tier of ["high", "balanced", "low"] as const) {
      const graph = buildFabricGraph({ devices, links, layout, theme, profile: profileFor(tier) });
      try {
        for (const r of materialsUnder(graph.scene)) if (isStroke(r.material)) out.push({ ...r, owner: `${theme}/${tier}/${r.owner}` });
      } finally {
        graph.dispose();
      }
    }
    const overlay = createFlowOverlay(readTokens(theme));
    try {
      for (const r of materialsUnder(overlay.group)) if (isStroke(r.material)) out.push({ ...r, owner: `${theme}/trace/${r.owner}` });
    } finally {
      overlay.dispose();
    }
  }
  return out;
}

describe("C5 item 8: no stroke the fabric draws is thinner than the 2 CSS px floor", () => {
  const strokes = everyStrokeTheAppBuilds();

  it("finds the whole class: cables, the uncollected outline and the trace's lines", () => {
    const owners = new Set(strokes.map((s) => s.owner.split("/").at(-1)!.replace(/:.*/, "")));
    // Not the guard — the guard is below, over whatever was found. This only proves the walk
    // reached the kinds of stroke the report named, so a walk that found nothing cannot pass.
    for (const kind of ["cables", "uncollected-edges", "trace-path", "trace-blocked", "trace-tether"]) {
      expect(owners, `the scene walk must reach ${kind}`).toContain(kind);
    }
  });

  it("draws every stroke with LineMaterial (a LineBasicMaterial is a 1 px hairline on every platform)", () => {
    const other = strokes.filter((s) => s.material.type !== "LineMaterial").map((s) => `${s.owner} ${s.material.type}`);
    expect(other).toEqual([]);
  });

  it("paints at least MIN_STROKE_PX per rail, in every theme and at every tier", () => {
    expect(MIN_STROKE_PX).toBe(2);
    const thin = strokes
      .map((s) => ({ owner: s.owner, px: paintedRailPx(s.material as LineMaterial) }))
      .filter((s) => s.px < MIN_STROKE_PX - 1e-6)
      .map((s) => `${s.owner} paints ${s.px.toFixed(2)} CSS px`);
    expect(thin).toEqual([]);
  });

  it("never lets a stroke's unpainted fragments occlude another stroke (no depth write)", () => {
    const writers = strokes.filter((s) => s.material.depthWrite).map((s) => s.owner);
    expect(writers, "a zero-coverage fragment that writes depth cuts its neighbour down to a sliver").toEqual([]);
  });

  it("holds the floor at the factory too: a caller asking for less gets the floor", () => {
    for (const rails of [1, 2, 4]) {
      const m = createCableMaterial("solid", 0.5, 1, { rails, railGapPx: 3 });
      try {
        expect(paintedRailPx(m), `${rails} rail(s)`).toBeGreaterThanOrEqual(MIN_STROKE_PX - 1e-6);
        expect(m.depthWrite).toBe(false);
      } finally {
        m.dispose();
      }
    }
  });

  it("has no stroke-material constructor outside the factory that enforces all this", () => {
    const dir = resolve(__dirname);
    const sources = [
      ...readdirSync(dir).map((f) => resolve(dir, f)),
      ...readdirSync(resolve(dir, "geometry")).map((f) => resolve(dir, "geometry", f)),
    ].filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\.(ts|tsx)$/.test(f));
    const offenders: string[] = [];
    for (const f of sources) {
      const text = readFileSync(f, "utf8");
      const ctor = /new\s+(LineMaterial|LineBasicMaterial|LineDashedMaterial)\s*\(/g;
      for (let m = ctor.exec(text); m !== null; m = ctor.exec(text)) {
        if (!f.endsWith(`geometry${"\\"}cables.ts`) && !f.endsWith("geometry/cables.ts")) offenders.push(`${f}: ${m[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

/* The brief half: design-brief §4.5 sets the 2 CSS px floor for EVERY stroke, and the factory above
   enforces it for every stroke the fabric builds. A table row in §4.4 (device representation) or
   §4.5 (link representation) that still specifies a thinner stroke is a spec the renderer can no
   longer honour — the uncollected outline was specified as 1.4 px after the floor made it 2 px.
   Derived from the tables, not from a list of rows: every absolute px width a row states is held
   to the floor; a relative `+N px` (hover) is a delta, not a width. */
describe("C5 item 8: the design brief specifies no stroke under the floor the renderer enforces", () => {
  it("every absolute px width in the §4.4/§4.5 tables is at least MIN_STROKE_PX", () => {
    const brief = readFileSync(resolve(__dirname, "../../docs/design-brief.md"), "utf8").split(/\r?\n/);
    const from = brief.findIndex((l) => l.startsWith("### 4.4"));
    const to = brief.findIndex((l) => l.startsWith("### 4.6"));
    expect(from, "the brief must still have §4.4").toBeGreaterThan(0);
    expect(to, "the brief must still have §4.6 after §4.4").toBeGreaterThan(from);
    const rows = brief.slice(from, to).filter((l) => l.startsWith("|") && !/^\|\s*-/.test(l));
    const widths: string[] = [];
    const thin: string[] = [];
    for (const row of rows) {
      for (const m of row.matchAll(/(\+)?\s?(\d+(?:\.\d+)?)\s?px\b/g)) {
        if (m[1] === "+") continue;
        widths.push(m[0]);
        if (Number(m[2]) < MIN_STROKE_PX - 1e-6) thin.push(`${m[0].trim()} in: ${row.slice(0, 80)}`);
      }
    }
    expect(widths.length, "the walk must find the brief's stroke widths at all").toBeGreaterThan(0);
    expect(thin).toEqual([]);
  });
});

/* The DOM half: lines the label layer draws ON the stage (a leader from a displaced name to its
   device). A pseudo-element drawn as a line — `content: ""` with a background — is a stroke, and a
   1 px one is the same tell on the stage as on the canvas. Chip borders and focus/hover outlines
   are UI chrome, not strokes standing for the network; they follow the design system's hairline
   rule (design-brief §3) and are out of this class by definition, not by a list. */
describe("C5 item 8: no line the label layer draws over the stage is under 2 CSS px", () => {
  it("every pseudo-element line in the fabric's stylesheets is at least MIN_STROKE_PX across", () => {
    const dir = resolve(__dirname);
    const sheets = readdirSync(dir).filter((f) => f.endsWith(".css"));
    expect(sheets.length).toBeGreaterThan(0);
    const thin: string[] = [];
    let lines = 0;
    for (const f of sheets) {
      const css = readFileSync(resolve(dir, f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      const rule = /([^{}]+)\{([^{}]*)\}/g;
      for (let m = rule.exec(css); m !== null; m = rule.exec(css)) {
        const [sel, body] = [m[1]!.trim(), m[2]!];
        if (!/::(after|before)/.test(sel) || !/content:\s*""/.test(body) || !/background(-color)?:/.test(body)) continue;
        const size = (prop: string): number | null => {
          const v = new RegExp(`(?:^|[;\\s])${prop}:\\s*([\\d.]+)px`).exec(body);
          return v === null ? null : Number(v[1]);
        };
        const across = [size("inline-size"), size("block-size"), size("width"), size("height")].filter(
          (v): v is number => v !== null,
        );
        if (across.length === 0) continue;
        lines += 1;
        const narrowest = Math.min(...across);
        if (narrowest < MIN_STROKE_PX) thin.push(`${f} ${sel}: ${narrowest}px`);
      }
    }
    expect(lines, "the walk must find the leader lines at all").toBeGreaterThan(0);
    expect(thin).toEqual([]);
  });
});
