/**
 * target-size.test.ts — a declared pointer target may not declare a floor below 24 px.
 *
 * THE DEFECT THIS PINS, as measured in the running application:
 *
 *   Twenty visible interactive controls rendered under 24 CSS px on one axis and stayed inside
 *   WCAG 2.5.8 only through its SPACING exception — which design-brief §3.2 allows, but only when
 *   the exception is enumerated in `docs/target-size-exceptions.md` with its measured spacing.
 *   That file does not exist, so every one of them was an unenumerated undersized target, which
 *   the brief calls a defect in as many words. Measured: `button.ui-cite` 97x16 to 203x16 (36 of
 *   them), `button.ui-chip__remove` 24.0x22.0, `input.hdr-query__input` 609.3x18.8. All three are
 *   now ≥ 24 px on both axes and owe nothing to the exception.
 *
 *   Two of the three were written the same way: a rule that says `cursor: pointer` — "this is a
 *   thing you click" — and in the same breath sets a block-axis minimum SMALLER than the floor
 *   (`.ui-cite { min-height: 1rem; cursor: pointer }`). That pairing is checkable from source, so
 *   it is checked here.
 *
 * WHAT THIS CANNOT DO, stated plainly so nobody reads it as more than it is:
 *
 *   - It is a rule-level scan, not a rendered measurement. A control whose floor comes from a
 *     parent, from a flex stretch, or from no declaration at all is invisible to it — the third
 *     defect above (`.ui-chip__remove`, which declared no block minimum and inherited 22 px from
 *     a border-box parent) would NOT have been caught by this test.
 *   - It cannot see the inline axis, which depends on content.
 *   The real measurement is the browser, in review/. This is the cheap net under it, and it
 *   catches the exact shape that shipped twice.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function cssFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) cssFiles(p, out);
    else if (p.endsWith(".css")) out.push(p);
  }
  return out;
}

const ROOT_FONT_PX = 16;
const FLOOR_PX = 24;

/** The size tokens, read from tokens.css rather than copied — a copy is a second thing to rot. */
function sizeTokens(): Map<string, number> {
  const css = readFileSync(join(SRC, "core/tokens.css"), "utf8");
  const out = new Map<string, number>();
  for (const m of css.matchAll(/(--[\w-]+):\s*([\d.]+)(rem|px)\s*;/g)) {
    out.set(m[1]!, m[3] === "rem" ? parseFloat(m[2]!) * ROOT_FONT_PX : parseFloat(m[2]!));
  }
  return out;
}

/** px, or null when the value is not a fixed length this scan can resolve. */
function toPx(value: string, tokens: Map<string, number>): number | null {
  const v = value.trim();
  if (/^[\d.]+px$/.test(v)) return parseFloat(v);
  if (/^[\d.]+rem$/.test(v)) return parseFloat(v) * ROOT_FONT_PX;
  const tok = v.match(/^var\(\s*(--[\w-]+)/);
  if (tok) return tokens.get(tok[1]!) ?? null;
  return null;
}

interface Rule {
  file: string;
  selector: string;
  body: string;
}

function pointerRules(): Rule[] {
  const out: Rule[] = [];
  for (const f of cssFiles(SRC)) {
    /* Comments first: this file's own explanations, and the stylesheets', quote the declarations
       being checked. A scan that cannot tell prose from code reads the explanation as the offence. */
    const css = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, " ");
    for (const block of css.split("}")) {
      const brace = block.indexOf("{");
      if (brace < 0) continue;
      const body = block.slice(brace + 1);
      if (!/cursor:\s*pointer/.test(body)) continue;
      out.push({
        file: relative(SRC, f).split("\\").join("/"),
        selector: block.slice(0, brace).trim().replace(/\s+/g, " "),
        body,
      });
    }
  }
  return out;
}

describe("a declared pointer target does not declare a sub-24px floor", () => {
  const tokens = sizeTokens();
  const rules = pointerRules();

  it("reads the size tokens from tokens.css — an empty token map would pass everything", () => {
    expect(tokens.get("--target-min")).toBe(FLOOR_PX);
    expect(tokens.size).toBeGreaterThan(10);
  });

  it("finds the pointer rules to check — an empty scan is not a pass", () => {
    expect(rules.length).toBeGreaterThan(20);
    const files = new Set(rules.map((r) => r.file));
    expect(files.has("ui/primitives.css")).toBe(true);
    expect(files.has("app/chrome.css")).toBe(true);
    expect(files.has("panels/PriorityQueue.css")).toBe(true);
  });

  it("covers the three controls the audit measured undersized", () => {
    /* The denominator gets pinned, not assumed: if one of these rules is renamed or loses its
       `cursor: pointer`, the check below silently stops looking at it. */
    const selectors = rules.map((r) => r.selector).join(" | ");
    for (const s of [".ui-cite", ".ui-chip__remove"]) {
      expect(selectors, `${s} is no longer among the scanned pointer rules`).toContain(s);
    }
  });

  it("declares no block-axis minimum below 24px", () => {
    const offenders: string[] = [];
    for (const r of rules) {
      for (const m of r.body.matchAll(/min-(?:height|block-size):\s*([^;]+);/g)) {
        const px = toPx(m[1]!, tokens);
        if (px !== null && px < FLOOR_PX) {
          offenders.push(`${r.file} :: ${r.selector} :: min ${m[1]!.trim()} = ${px}px`);
        }
      }
    }
    expect(
      offenders,
      `a rule that says "cursor: pointer" is a rule that says "this is a target", and design-brief\n` +
        `§3.2 puts the floor at ${FLOOR_PX}px with the hit area grown by padding — never by shrinking\n` +
        `the target. Where a target genuinely cannot reach it, the spacing exception applies ONLY\n` +
        `once it is enumerated in docs/target-size-exceptions.md with its measured spacing:\n` +
        offenders.join("\n"),
    ).toEqual([]);
  });
});
