/**
 * DataGrid.a11y-tree.test.ts — no render-skipping on anything the accessibility tree announces.
 *
 * Measured defect (independent a11y audit, 2026-09-22): `.ag__row--data { content-visibility: auto }`
 * kept every row node but Chromium pruned the subtree of each skipped row, so at load 76 of the
 * findings grid's 152 rows exposed no gridcell, no rowheader and an empty accessible name
 * (CDP Accessibility.getFullAXTree at 1920x1080: rowheader = 70 for 146 data rows). The rule's own
 * comment claimed the opposite. After removal: rowheader = 146, unnamed rows = 0.
 *
 * The guard is on the CLASS, not the one selector: `content-visibility: auto | hidden` skips the
 * subtree of whatever element it lands on, and that element — a row, a cell, a group, a pane
 * wrapping a grid — is exactly what the tree then misreports. So no stylesheet under src/ may
 * declare it with a skipping value. Offscreen rows are skipped only by real windowing, which
 * removes them from the DOM and keeps aria-rowcount / aria-rowindex honest (GridWindowing).
 *
 * This is a source-text tripwire. The behavioural proof is the live tree:
 * `node review/a11y-ax-rows.mjs` must print rowheader == dataRows and unnamedRows == 0.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function cssFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...cssFiles(p));
    else if (name.endsWith(".css")) out.push(p);
  }
  return out;
}

const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

describe("accessibility tree: nothing announced is render-skipped", () => {
  const files = cssFiles(SRC);

  it("finds the stylesheets it is guarding (a scan over nothing proves nothing)", () => {
    expect(files.some((f) => f.endsWith(join("panels", "DataGrid.css")))).toBe(true);
    expect(files.length).toBeGreaterThan(5);
  });

  it("no stylesheet declares content-visibility with a render-skipping value", () => {
    const offenders: string[] = [];
    for (const f of files) {
      const css = stripComments(readFileSync(f, "utf8"));
      for (const m of css.matchAll(/content-visibility\s*:\s*([^;}]+)/g)) {
        const value = m[1]!.trim().toLowerCase();
        if (value !== "visible") offenders.push(`${relative(SRC, f)}: content-visibility: ${value}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("the tripwire itself fires on the shape that shipped", () => {
    const shipped = ".ag__row--data {\n  content-visibility: auto;\n}";
    expect([...stripComments(shipped).matchAll(/content-visibility\s*:\s*([^;}]+)/g)]).toHaveLength(1);
  });
});
