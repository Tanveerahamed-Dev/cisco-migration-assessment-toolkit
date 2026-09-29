/**
 * role-glyph.test.tsx — an OBSERVED role is never drawn as "role not observed" (disc-app-sample-assumptions #1).
 *
 * The scene mapped only access and distribution to a glyph and drew every other role — core, spine, backbone,
 * which the engine does emit — with the open-rectangle "role not observed" mark, while the legend counted those
 * devices in a separate "Other role" row. An observed fact rendered as absence. Case was handled differently in
 * the legend ("Access" was an Other role there) and the scene.
 *
 * Now one owner, src/core/roles.ts (normalizeRole / roleGlyphClass), classifies every role for the scene, the
 * chassis glyph set and the legend, and "other" has its own glyph: a single solid bar, the shape the legend's
 * Other-role row draws, geometrically distinct from the open rectangle of "unobserved".
 *
 * The reference sample has no role outside access/distribution (measured: 3 null, 19 access, 4 distribution), so
 * every test here runs on a SYNTHETIC fleet: the sample's devices and links with roles re-stated.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { roleGlyphClass } from "../core/roles";
import { computeLayout } from "./layout";
import { buildFabricGraph } from "./scene";
import { buildRoleGlyph, ROLE_GLYPHS } from "./geometry/chassis";
import { profileFor } from "./quality";
import { FabricLegend } from "./FabricLegend";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  document.body.innerHTML = "";
});

const base = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
/** Roles re-stated round-robin: an unknown-to-the-sample role in several spellings, the two mapped roles in
 *  other cases and with whitespace, a blank string, and null. */
const ROLES: (string | null)[] = ["core", "Spine ", "ACCESS", " distribution", "", null, "backbone", "access"];
const devices: Device[] = base.map((d, i) => ({ ...d, role: ROLES[i % ROLES.length] ?? null }));
const expectedCount = (cls: string): number => devices.filter((d) => roleGlyphClass(d.role) === cls).length;

describe("the scene draws each role through the one owner", () => {
  it("precondition: the synthetic fleet has devices in all four classes", () => {
    for (const cls of ["access", "distribution", "other", "unobserved"]) expect(expectedCount(cls), cls).toBeGreaterThan(0);
  });

  it("an observed role outside access/distribution gets the 'other' glyph, never the 'unobserved' one", () => {
    const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
    const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("high") });
    try {
      const counts = Object.fromEntries(graph.roleGlyphs.map((m) => [m.name, m.count]));
      expect(counts).toEqual({
        "role:access": expectedCount("access"),
        "role:distribution": expectedCount("distribution"),
        "role:other": expectedCount("other"),
        "role:unobserved": expectedCount("unobserved"),
      });
      // "core" alone, the role the owner decision names.
      expect(devices.filter((d) => d.role === "core").every((d) => roleGlyphClass(d.role) === "other")).toBe(true);
      // The unobserved glyph counts exactly the devices with no stated role (null or blank) — nothing observed.
      expect(counts["role:unobserved"]).toBe(devices.filter((d) => d.role === null || d.role.trim() === "").length);
    } finally {
      graph.dispose();
    }
  });

  it("the chassis glyph set is exactly the owner's classes, so a class cannot go without a glyph", () => {
    expect([...ROLE_GLYPHS].sort()).toEqual(["access", "distribution", "other", "unobserved"]);
  });
});

describe("the 'other' glyph is the legend's Other-role mark and is not the 'unobserved' mark", () => {
  const BOX_VERTS = 36; // a non-indexed box
  const parts = (g: ReturnType<typeof buildRoleGlyph>): number => g.getAttribute("position").count / BOX_VERTS;

  it("3-D: 'other' is one solid bar; 'unobserved' is the four-bar open rectangle", () => {
    const other = buildRoleGlyph("other");
    const unobserved = buildRoleGlyph("unobserved");
    try {
      expect(parts(other)).toBe(1);
      other.computeBoundingBox();
      const b = other.boundingBox!;
      expect(b.max.x - b.min.x, "a bar: wider than it is tall").toBeGreaterThan(3 * (b.max.y - b.min.y));
      expect(parts(unobserved)).toBe(4);
    } finally {
      other.dispose();
      unobserved.dispose();
    }
  });

  it("legend: the Other-role row is one solid horizontal stroke and counts the owner's 'other' class", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<FabricLegend id="lg" devices={devices} links={links} />));
    const show = host.querySelector<HTMLButtonElement>('[data-testid="fabric3d-legend-show"]');
    if (show) act(() => show.click());
    const group = [...host.querySelectorAll(".fabric3d-legend__group")].find((g) => g.textContent?.includes("role"));
    expect(group).toBeDefined();
    const rows = [...group!.querySelectorAll(".fabric3d-legend__row")];
    const row = (name: string): Element => {
      const r = rows.find((x) => x.querySelector(".fabric3d-legend__text")?.textContent?.startsWith(name));
      expect(r, name).toBeDefined();
      return r!;
    };
    const count = (name: string): number => Number(row(name).querySelector(".fabric3d-legend__count")?.textContent);
    expect(count("Access")).toBe(expectedCount("access"));
    expect(count("Distribution")).toBe(expectedCount("distribution"));
    expect(count("Other role")).toBe(expectedCount("other"));
    expect(count("Role not observed")).toBe(expectedCount("unobserved"));

    const marks = [...row("Other role").querySelectorAll("svg > *")];
    expect(marks).toHaveLength(1);
    expect(marks[0]!.getAttribute("stroke-dasharray")).toBeNull();
    expect(marks[0]!.getAttribute("d")).toMatch(/^M\s*[\d.]+\s+([\d.]+)\s+H\s*[\d.]+$/);
    // ...and it is drawn differently from the not-observed row.
    expect(row("Role not observed").innerHTML).not.toBe(row("Other role").innerHTML);
    act(() => root.unmount());
  });
});

describe("the class: no role classification outside the owner in fabric3d", () => {
  /* A guard on scene.ts and FabricLegend.tsx alone would be a named subset. The class is "a module in the 3-D
     subsystem deciding what a role IS" — comparing a role to a literal or to null, or case-folding it — and the
     only legal spelling is a call to roles.ts. Every non-test source in src/fabric3d is scanned. */
  const DIR = dirname(fileURLToPath(import.meta.url));
  const sources = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? sources(join(dir, e.name)) : /\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) ? [join(dir, e.name)] : [],
    );
  const CLASSIFY = /\brole\s*[!=]==|\.role\s*\??\.\s*(toLowerCase|toUpperCase|trim)\b|roles\.has\(\s*\w+\.role\s*\)/g;
  /* Sites in files this cluster does not own, routed to their owner (P3D: layout.ts, Fabric3D.tsx). Each entry
     must STILL match, so the day it is fixed this list goes red until the entry is removed. */
  const PENDING: Record<string, string[]> = {
    "layout.ts": ["role !==", ".role.toLowerCase"],
    "Fabric3D.tsx": ["role !==", "roles.has(d.role)"],
  };
  const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
  const found = new Map<string, string[]>();
  for (const f of sources(DIR)) {
    const hits = [...strip(readFileSync(f, "utf8")).matchAll(CLASSIFY)].map((m) => m[0].replace(/\s+/g, " "));
    if (hits.length > 0) found.set(f.slice(DIR.length + 1).replace(/\\/g, "/"), hits);
  }

  it("scanned the subsystem (the file set is not empty)", () => {
    expect(sources(DIR).length).toBeGreaterThan(20);
  });

  it("no unlisted classification site", () => {
    const unlisted = [...found].flatMap(([f, hits]) => hits.filter((h) => !(PENDING[f] ?? []).some((p) => h.includes(p))).map((h) => `${f}: ${h}`));
    expect(unlisted).toEqual([]);
  });

  it("every pending entry is still a live site (remove it once its owner routes the site through roles.ts)", () => {
    const stale = Object.entries(PENDING).flatMap(([f, ps]) => ps.filter((p) => !(found.get(f) ?? []).some((h) => h.includes(p))).map((p) => `${f}: ${p}`));
    expect(stale).toEqual([]);
  });
});
