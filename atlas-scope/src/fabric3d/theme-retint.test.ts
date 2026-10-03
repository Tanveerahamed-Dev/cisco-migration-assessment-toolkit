/**
 * theme-retint.test.ts — a live theme switch leaves the scene graph exactly as a fresh build in the
 * new theme would (acceptance C4).
 *
 * MEASURED before the fix (C4 re-grade refuter, release build, 1920x1080): after clicking the real
 * Light/Dark control the operational-state rings kept the previous theme's per-instance colours
 * until a reload — a light ring pixel was (161,179,171), 1.87:1 on the ground, where a fresh light
 * load gives (100,118,111), 4.1:1. `applyTheme` re-tinted materials, cables, the body and LED
 * instances by a hand-kept list, and the rings were not on it: their colour was written once, at
 * build, from the theme in force then.
 *
 * The guard is the CLASS, not the rings: the scene is built in theme A and switched to B through the
 * same code the live switch runs, then compared against a scene built fresh in B, object by object,
 * over EVERYTHING a traversal of the scene graph reaches — per-instance colours, every geometry
 * attribute, every colour, number and uniform a material carries, and every light. Nothing is
 * listed by name, so a per-instance colour added tomorrow is covered the day it is written.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  BufferAttribute,
  Color,
  InstancedBufferAttribute,
  InstancedMesh,
  InterleavedBufferAttribute,
  Light,
  Matrix3,
  Matrix4,
  Mesh,
  Texture,
  Vector2,
  Vector3,
  Vector4,
  type Material,
  type Object3D,
} from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph, retintFabricGraph, type FabricGraph } from "./scene";
import { profileFor } from "./quality";
import { readTokens, type ThemeName, type TokenPalette } from "./materials";
import { createLighting } from "./lighting";
import { createFlowOverlay } from "./flow";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });

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
  expect(rootBlock.length).toBeGreaterThan(100);
  expect(darkBlock.length).toBeGreaterThan(100);
  const host = document.createElement("div");
  const vars = { ...decls(rootBlock), ...(theme === "dark" ? decls(darkBlock) : {}) };
  for (const [k, v] of Object.entries(vars)) host.style.setProperty(k, v);
  document.body.appendChild(host);
  return host;
}

/** The scene-graph parts the live switch re-tints (scene.ts `applyTheme`), built as createScene builds them. */
interface Built {
  graph: FabricGraph;
  retint(tokens: TokenPalette): void;
}
function build(theme: ThemeName, root: HTMLElement, tier: "low" | "high"): Built {
  const profile = profileFor(tier);
  const graph = buildFabricGraph({ devices, links, layout, theme, profile, tokenRoot: root });
  const lighting = createLighting(graph.tokens, profile);
  lighting.fit(layout.bounds);
  graph.scene.add(lighting.group);
  const flow = createFlowOverlay(graph.tokens);
  graph.scene.add(flow.group);
  return {
    graph,
    retint(tokens: TokenPalette): void {
      // The same three calls, in the same order, as applyTheme makes on the scene graph.
      retintFabricGraph(graph, tokens);
      lighting.retint(tokens);
      flow.retint(tokens);
    },
  };
}

const IGNORED_KEYS = new Set(["id", "uuid", "version", "_listeners", "userData"]);

/** Every value a material (or a uniform block) carries that a theme could decide, flattened to numbers. */
function fingerprint(value: unknown, path: string, out: Map<string, number[]>, depth = 0): void {
  if (depth > 4 || value === null || value === undefined) return;
  if (typeof value === "number") out.set(path, [value]);
  else if (typeof value === "boolean") out.set(path, [value ? 1 : 0]);
  else if (value instanceof Color) out.set(path, [value.r, value.g, value.b]);
  else if (value instanceof Vector2 || value instanceof Vector3 || value instanceof Vector4) out.set(path, value.toArray());
  else if (value instanceof Matrix3 || value instanceof Matrix4) out.set(path, [...value.elements]);
  else if (value instanceof Texture) return; // identity differs per build; its pixels are not theme-derived here
  else if (typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (IGNORED_KEYS.has(k) || typeof v === "function") continue;
      fingerprint(v, `${path}.${k}`, out, depth + 1);
    }
  }
}

/** An attribute's values item by item, so an INTERLEAVED one (the cable colours) is read too, not its empty `array`. */
function attributeArray(a: BufferAttribute | InstancedBufferAttribute | InterleavedBufferAttribute): number[] {
  const out: number[] = [];
  const get = [a.getX, a.getY, a.getZ, a.getW] as const;
  for (let i = 0; i < a.count; i += 1) {
    for (let k = 0; k < Math.min(a.itemSize, 4); k += 1) out.push(get[k]!.call(a, i));
  }
  return out;
}

/** One object's theme-relevant state: per-instance colour, every geometry attribute, its materials, its light. */
function stateOf(o: Object3D): Map<string, number[]> {
  const out = new Map<string, number[]>();
  if (o instanceof InstancedMesh && o.instanceColor !== null) out.set("instanceColor", attributeArray(o.instanceColor));
  const geometry = (o as Mesh).geometry as Mesh["geometry"] | undefined;
  if (geometry !== undefined && geometry.attributes !== undefined) {
    for (const [name, attr] of Object.entries(geometry.attributes)) {
      out.set(`geometry.${name}`, attributeArray(attr));
    }
  }
  const material = (o as Mesh).material as Material | Material[] | undefined;
  if (material !== undefined) {
    (Array.isArray(material) ? material : [material]).forEach((m, i) => fingerprint(m, `material[${i}]`, out));
  }
  if (o instanceof Light) {
    out.set("light.color", [o.color.r, o.color.g, o.color.b]);
    out.set("light.intensity", [o.intensity]);
  }
  return out;
}

function objects(graph: FabricGraph): Object3D[] {
  const all: Object3D[] = [];
  graph.scene.traverse((o) => all.push(o));
  return all;
}

/** Every difference between two scenes, by traversal position and object name. Empty means identical. */
function differences(switched: FabricGraph, fresh: FabricGraph): string[] {
  const a = objects(switched);
  const b = objects(fresh);
  const out: string[] = [];
  if (a.length !== b.length) out.push(`object count ${a.length} vs ${b.length}`);
  for (let i = 0; i < Math.min(a.length, b.length); i += 1) {
    const x = a[i]!;
    const y = b[i]!;
    const where = `#${i} ${x.type} "${x.name}"`;
    if (x.type !== y.type || x.name !== y.name) {
      out.push(`${where} pairs with ${y.type} "${y.name}"`);
      continue;
    }
    const sx = stateOf(x);
    const sy = stateOf(y);
    for (const key of new Set([...sx.keys(), ...sy.keys()])) {
      const vx = sx.get(key);
      const vy = sy.get(key);
      if (vx === undefined || vy === undefined) {
        out.push(`${where} ${key}: present in only one scene`);
        continue;
      }
      if (vx.length !== vy.length) {
        out.push(`${where} ${key}: length ${vx.length} vs ${vy.length}`);
        continue;
      }
      let worst = 0;
      let at = -1;
      for (let k = 0; k < vx.length; k += 1) {
        const d = Math.abs((vx[k] ?? 0) - (vy[k] ?? 0));
        if (d > worst) {
          worst = d;
          at = k;
        }
      }
      if (worst > 1e-6) out.push(`${where} ${key}[${at}]: switched ${vx[at]} vs fresh ${vy[at]}`);
    }
  }
  return out;
}

describe("a live theme switch equals a fresh build in the new theme (C4)", () => {
  const roots = { light: shippedRoot("light"), dark: shippedRoot("dark") } as const;

  it("the shipped palettes were parsed and the two themes really differ", () => {
    expect(readTokens("light", roots.light).missing).toEqual([]);
    expect(readTokens("dark", roots.dark).missing).toEqual([]);
    expect(readTokens("light", roots.light).css["--state-up"]).not.toBe(readTokens("dark", roots.dark).css["--state-up"]);
  });

  it("positive control: the traversal reaches the state rings, and every one of them carries per-instance colour", () => {
    const { graph } = build("dark", roots.dark, "low");
    try {
      const reached = new Set(objects(graph));
      expect(graph.stateRings.length).toBeGreaterThan(0);
      for (const ring of graph.stateRings) {
        expect(reached.has(ring), ring.name).toBe(true);
        if (ring.count > 0) expect(ring.instanceColor, ring.name).not.toBeNull();
      }
      const coloured = objects(graph).filter((o) => o instanceof InstancedMesh && o.instanceColor !== null);
      expect(coloured.map((o) => o.name)).toEqual(expect.arrayContaining(graph.stateRings.filter((r) => r.count > 0).map((r) => r.name)));
      // ...and the comparison is not vacuous: a scene built in the other theme differs from it.
      const other = build("light", roots.light, "low");
      try {
        expect(differences(graph, other.graph).length).toBeGreaterThan(0);
      } finally {
        other.graph.dispose();
      }
    } finally {
      graph.dispose();
    }
  });

  for (const tier of ["low", "high"] as const) {
    for (const [from, to] of [
      ["dark", "light"],
      ["light", "dark"],
    ] as const) {
      it(`${tier}: built ${from}, switched to ${to} === built fresh in ${to}, over every object in the scene graph`, () => {
        const switched = build(from, roots[from], tier);
        const fresh = build(to, roots[to], tier);
        try {
          // The fresh scene is NOT re-tinted: a re-tint that disagreed with the build would then agree
          // with itself on both sides, which is the drift this test exists to see.
          switched.retint(readTokens(to, roots[to]));
          expect(differences(switched.graph, fresh.graph)).toEqual([]);
        } finally {
          switched.graph.dispose();
          fresh.graph.dispose();
        }
      });
    }
  }
});
