/**
 * scene.data-signature.test.ts — setData never keeps a stale glyph, ring, cable or position.
 *
 * FOUND WHILE RE-MEASURING THE DRAW-CALL BUDGET FOR THE "other" ROLE GLYPH (phase 3). The live scene was handed the
 * sample with a third of its roles re-stated as "core" through `setData`; the draw calls AND the triangle count
 * came back identical (71 / 153,443), because `setData` took its repaint-only fast path: its signature was
 * `id/kind/collected` per device and `id:a>b` per link. Every other field the graph build reads — the role (which
 * glyph), the operational state (which ring), a link's status (which cable), the layout (where) — could change
 * with the old glyphs, rings, cables and positions left on screen. Only the band tint is repainted in place.
 *
 * `sceneDataSignature` is now everything the build reads EXCEPT the one field the fast path repaints (the band),
 * plus the layout's node positions. Stated as a class, not a list of fields: every device field except `band`,
 * and every link field, is perturbed below and must move the signature.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { sceneDataSignature } from "./scene";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const base = sceneDataSignature(devices, links, layout);

/** A value guaranteed to differ from `v`, of a JSON-representable shape. */
const perturb = (v: unknown): unknown =>
  v === null ? "perturbed" : typeof v === "number" ? v + 1 : typeof v === "boolean" ? !v : typeof v === "string" ? `${v}~` : Array.isArray(v) ? [...v, "perturbed"] : { ...(v as object), perturbed: true };

describe("sceneDataSignature", () => {
  it("is stable for the same data", () => {
    expect(sceneDataSignature(devices.map((d) => ({ ...d })), links.map((l) => ({ ...l })), layout)).toBe(base);
  });

  it("a role re-stated to 'core' moves it (the case that surfaced this)", () => {
    const ds = devices.map((d, i) => (i === 0 ? { ...d, role: "core" } : d));
    expect(sceneDataSignature(ds, links, layout)).not.toBe(base);
  });

  it("every device field except the repainted band moves it", () => {
    const d0 = devices[0]!;
    const fields = Object.keys(d0) as (keyof Device)[];
    expect(fields.length).toBeGreaterThan(10);
    const inert = fields.filter((f) => f !== "band" && sceneDataSignature([{ ...d0, [f]: perturb(d0[f]) } as Device, ...devices.slice(1)], links, layout) === base);
    expect(inert).toEqual([]);
  });

  it("the band alone does NOT move it: that is the one change the fast path repaints in place", () => {
    const ds = devices.map((d) => ({ ...d, band: d.band === "Poor" ? ("Critical" as const) : ("Poor" as const) }));
    expect(sceneDataSignature(ds, links, layout)).toBe(base);
  });

  it("every link field moves it", () => {
    const l0 = links[0]!;
    const fields = Object.keys(l0) as (keyof Link)[];
    const inert = fields.filter((f) => sceneDataSignature(devices, [{ ...l0, [f]: perturb(l0[f]) } as Link, ...links.slice(1)], layout) === base);
    expect(inert).toEqual([]);
  });

  it("a moved node moves it", () => {
    const n0 = layout.nodes[0]!;
    const moved = { ...layout, nodes: [{ ...n0, x: n0.x + 1 }, ...layout.nodes.slice(1)] };
    expect(sceneDataSignature(devices, links, moved)).not.toBe(base);
  });

  it("setData's fast path and the graph's stored signature both use it", () => {
    const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "scene.ts"), "utf8");
    expect(src).toMatch(/signature: sceneDataSignature\(devices, links, layout\)/);
    expect(src).toMatch(/const signature = sceneDataSignature\(devices, links, nextLayout\);\s*\n\s*if \(signature === graph\.signature\)/);
    expect(src).not.toMatch(/topologySignature/);
  });
});
