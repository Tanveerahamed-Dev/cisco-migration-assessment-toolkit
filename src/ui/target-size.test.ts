/**
 * target-size.test.ts — a declared pointer target may not declare a size below 24 px.
 *
 * THE DEFECT THIS PINS, as measured in the running application:
 *
 *   Twenty visible interactive controls rendered under 24 CSS px on one axis and stayed inside
 *   WCAG 2.5.8 only through its SPACING exception — which design-brief §3.2 allows, but only when
 *   the exception is enumerated with its measured spacing. No enumeration existed, so every one of
 *   them was an unenumerated undersized target, which the brief calls a defect in as many words.
 *   Measured: `button.ui-cite` 97x16 to 203x16 (36 of them), `button.ui-chip__remove` 24.0x22.0,
 *   `input.hdr-query__input` 609.3x18.8. All three are now ≥ 24 px on both axes and owe nothing to
 *   the exception.
 *
 *   Two of the three were written the same way: a rule that says `cursor: pointer` — "this is a
 *   thing you click" — and in the same breath sets a block-axis minimum SMALLER than the floor
 *   (`.ui-cite { min-height: 1rem; cursor: pointer }`). That pairing is checkable from source, so
 *   it is checked here.
 *
 * WIDENED 2026-09-23 (acceptance D5, repair wave 3). The scan used to select rules by the literal
 * `cursor: pointer`, a NAMED SUBSET of the class it meant. The Inspector's resize divider —
 * `role="separator"`, `cursor: row-resize`, `block-size: var(--sp-2)` — rendered 760x8 at 1440 and
 * 1160x8 at 1920 (a 60 px drag moved the Inspector 316 -> 376) and was invisible to it twice over:
 * its cursor was not `pointer`, and its size was a `block-size`, not a minimum. A pointer target is
 * now:
 *   - any rule whose `cursor` is an OPERABLE value — everything except the values that say "nothing
 *     to operate here" (default, auto, text, not-allowed, wait, help …). `pointer`, `grab`, `move`,
 *     every `*-resize`, and whatever cursor a future control picks, are in by construction; and
 *   - any rule for an element the markup declares `role="separator"` (read from the .tsx sources),
 *     whatever its cursor, because a separator in this product is a resize handle.
 * Both axes are checked, and fixed sizes as well as minimums.
 *
 * NO EXEMPTIONS. WCAG 2.5.8 grants its spacing exception, and design-brief §3.2 accepts one only
 * when it is enumerated with measured spacing. This scan reads no exemption list, and none exists;
 * the last test below fails if one appears without being wired in, so a list can never be written
 * that this scan silently ignores.
 *
 * WHAT THIS CANNOT DO, stated plainly so nobody reads it as more than it is:
 *
 *   - It is a rule-level scan, not a rendered measurement. A control whose floor comes from a
 *     parent, from a flex stretch, or from no declaration at all is invisible to it — the third
 *     defect above (`.ui-chip__remove`, which declared no block minimum and inherited 22 px from
 *     a border-box parent) would NOT have been caught by this test.
 *   - It cannot see a size that depends on content.
 *   The real measurement is the browser (getBoundingClientRect); this is the cheap net under it,
 *   and it catches the exact shapes that shipped.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function filesUnder(dir: string, ext: RegExp, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) filesUnder(p, ext, out);
    else if (ext.test(p)) out.push(p);
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
  const tok = v.match(/^var\(\s*(--[\w-]+)\s*\)$/);
  if (tok) return tokens.get(tok[1]!) ?? null;
  /* `calc(<length> * <n>)`, the one calc shape the stylesheets use for a target size. */
  const mul = v.match(/^calc\(\s*(.+?)\s*\*\s*([\d.]+)\s*\)$/);
  if (mul) {
    const base = toPx(mul[1]!, tokens);
    return base === null ? null : base * parseFloat(mul[2]!);
  }
  return null;
}

/** Cursor values that say "there is nothing to operate here". Every OTHER value marks a target. */
const INERT_CURSORS = new Set([
  "default", "auto", "text", "vertical-text", "not-allowed", "no-drop", "wait", "progress", "help", "none",
  "inherit", "initial", "unset", "revert", "revert-layer",
]);

interface Sheet {
  file: string;
  css: string;
}

interface Rule {
  file: string;
  selector: string;
  body: string;
  /** Why this rule is a target rule — the cursor value, or the separator class it styles. */
  why: string;
}

/** Class names the markup puts on `role="separator"` elements, read from the JSX opening tags. */
function separatorClasses(sources: readonly string[]): Set<string> {
  const out = new Set<string>();
  for (const src of sources) {
    for (const tag of src.matchAll(/<[A-Za-z][\w.]*\b[^<>]*?\brole=(?:"separator"|\{\s*"separator"\s*\})[^<>]*?>/g)) {
      const cls = tag[0].match(/\bclassName=(?:"([^"]*)"|\{\s*"([^"]*)"\s*\})/);
      for (const c of (cls?.[1] ?? cls?.[2] ?? "").split(/\s+/)) if (c) out.add(c);
    }
  }
  return out;
}

function targetRules(sheets: readonly Sheet[], separators: ReadonlySet<string>): Rule[] {
  const out: Rule[] = [];
  for (const { file, css: raw } of sheets) {
    /* Comments first: this file's own explanations, and the stylesheets', quote the declarations
       being checked. A scan that cannot tell prose from code reads the explanation as the offence. */
    const css = raw.replace(/\/\*[\s\S]*?\*\//g, " ");
    for (const block of css.split("}")) {
      const brace = block.lastIndexOf("{");
      if (brace < 0) continue;
      const body = block.slice(brace + 1);
      const selector = block.slice(0, brace).trim().replace(/\s+/g, " ");
      const cursor = body.match(/(?:^|[;\s])cursor:\s*([a-z-]+)/)?.[1];
      /* The box a reader hits is the element, not a drawn ::before/::after decoration of it. */
      const boxSelectors = selector.split(",").map((s) => s.trim()).filter((s) => !/::?(?:before|after)\b/.test(s));
      const sep = [...separators].find((c) => boxSelectors.some((s) => new RegExp(`\\.${c}(?![\\w-])`).test(s)));
      let why: string | null = null;
      if (cursor !== undefined && !INERT_CURSORS.has(cursor) && boxSelectors.length > 0) why = `cursor: ${cursor}`;
      else if (sep !== undefined) why = `role="separator" .${sep}`;
      if (why === null) continue;
      out.push({ file, selector, body, why });
    }
  }
  return out;
}

const BLOCK = /(?:^|[;\s])((?:min-)?(?:height|block-size)):\s*([^;]+);/g;
const INLINE = /(?:^|[;\s])((?:min-)?(?:width|inline-size)):\s*([^;]+);/g;

function offendersIn(rules: readonly Rule[], tokens: Map<string, number>): string[] {
  const out: string[] = [];
  for (const r of rules) {
    for (const re of [BLOCK, INLINE]) {
      for (const m of r.body.matchAll(re)) {
        const px = toPx(m[2]!, tokens);
        if (px !== null && px < FLOOR_PX) out.push(`${r.file} :: ${r.selector} [${r.why}] :: ${m[1]} ${m[2]!.trim()} = ${px}px`);
      }
    }
  }
  return out;
}

const repoSheets = (): Sheet[] =>
  filesUnder(SRC, /\.css$/).map((p) => ({ file: relative(SRC, p).split("\\").join("/"), css: readFileSync(p, "utf8") }));
const repoSeparators = (): Set<string> =>
  separatorClasses(filesUnder(SRC, /\.tsx$/).filter((p) => !/\.test\.tsx$/.test(p)).map((p) => readFileSync(p, "utf8")));

describe("a declared pointer target does not declare a size below 24px", () => {
  const tokens = sizeTokens();
  const separators = repoSeparators();
  const rules = targetRules(repoSheets(), separators);

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

  it("reaches every resize handle the markup declares, not only `cursor: pointer`", () => {
    /* Derived, then pinned against what the audit found: the three separators in the product today.
       If the derivation breaks, this names which one fell out of the scan. */
    for (const c of ["splitter", "ag__resizer", "inspector__divider"]) {
      expect(separators, `role="separator" .${c} is no longer read from the markup`).toContain(c);
      expect(
        rules.some((r) => r.selector.split(",").some((s) => new RegExp(`\\.${c}(?![\\w-])`).test(s))),
        `.${c} is no longer among the scanned target rules`,
      ).toBe(true);
    }
    const cursors = new Set(rules.map((r) => r.why));
    expect(cursors).toContain("cursor: row-resize");
    expect(cursors).toContain("cursor: col-resize");
  });

  it("KNOWN ANSWER: the widened scan fires on planted rules of every shape it claims to catch", () => {
    const planted: Sheet[] = [
      {
        file: "planted.css",
        css: `
          /* .comment-only { cursor: row-resize; block-size: 2px; } */
          .p-rowresize { cursor: row-resize; block-size: var(--sp-2); }
          .p-grab { touch-action: none; cursor: grab; height: 8px; }
          .p-colresize { cursor: col-resize; inline-size: 6px; }
          .p-future, .p-other { cursor: zoom-in; min-width: 1rem; }
          .p-sep { block-size: 8px; }
          .p-sep::after { block-size: 1px; }
          .p-ok { cursor: pointer; min-height: var(--target-min); }
          .p-inert { cursor: not-allowed; height: 4px; }
          .p-calc { cursor: col-resize; inline-size: calc(var(--sp-3) * 2); }
        `,
      },
    ];
    const plantedSeps = separatorClasses([`<div role="separator" tabIndex={0} className="p-sep" onPointerDown={f} />`]);
    expect([...plantedSeps]).toEqual(["p-sep"]);
    const found = offendersIn(targetRules(planted, plantedSeps), tokens).map((o) => o.split(" :: ")[1]!.split(" [")[0]);
    expect(found.sort()).toEqual([".p-colresize", ".p-future, .p-other", ".p-grab", ".p-rowresize", ".p-sep"].sort());
  });

  it("declares no size below 24px on either axis", () => {
    const offenders = offendersIn(rules, tokens);
    expect(
      offenders,
      `a rule that says "this is a target" — an operable cursor, or a role="separator" handle — may not\n` +
        `size itself under ${FLOOR_PX}px. design-brief §3.2: the hit area is grown by padding or an overlay,\n` +
        `never by shrinking the target. This scan honours no exemption (see the file header):\n` +
        offenders.join("\n"),
    ).toEqual([]);
  });

  it("no target-size exemption list exists that this scan would be silently ignoring", () => {
    /* design-brief §3.2 names docs/target-size-exceptions.md as the place a genuine spacing exception
       is enumerated. None is needed today. If one is ever written, this scan must be taught to read
       it — until then its existence would be a list of exemptions nothing enforces. */
    expect(existsSync(resolve(SRC, "..", "docs", "target-size-exceptions.md"))).toBe(false);
  });
});
