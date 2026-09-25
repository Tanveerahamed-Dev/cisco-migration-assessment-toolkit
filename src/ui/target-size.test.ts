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

/* ── WIDENED 2026-09-25 (acceptance D1/D5, repair wave 6) ─────────────────────────────────────────
 *
 * THE HOLE, MEASURED. `.fabric3d-pointer` — the off-view finding pointer — rendered 141.23 x 16.84
 * CSS px in both themes, and a click at its centre re-framed the camera: a working target, 7 px under
 * the floor. The scan above passed it, because the rule declared NO size at all (`padding: 1px
 * var(--sp-1); font-size: var(--fs-0); line-height: 1.35; cursor: pointer`), and a scan that only
 * judges the sizes a rule declares has nothing to judge in a rule that declares none. Its height was
 * the height of one line of 11 px text plus 2 px of padding, and that is readable from source.
 *
 * And the element was a `<span onClick>` with no role and no tabindex: a target by what it DOES,
 * which no census that selects by role, tabindex or a cursor value can be relied on to find. So a
 * target rule is now ALSO any rule for a class the markup puts on an element carrying a pointer
 * handler (onClick, onPointerDown, onMouseDown, …), whatever its cursor, role or tabindex.
 *
 * THE BOX A RULE LEAVES TO ITS TEXT. For every target rule, every rule that styles the same element —
 * the subject compound carries one of its classes, or a class the markup puts on the same element
 * (`className="jsonview__row jsonview__row--more"`) — is gathered. A block-axis size declared by any
 * of them is judged by the scan above. When NONE declares one and the gathered rules set the text's
 * own metrics (font-size or line-height), the box is one line of that text plus the block padding
 * and borders, and that line box is computed: `line-height` (unitless x font-size, or a length;
 * 1.2 x font-size when unset) + 2 x padding-block + 2 x border-block. A font-size nobody in the group
 * sets is the SMALLEST type token (read from tokens.css), because an inherited size can be that
 * small. Under 24 px, it fails: the content box CAN fall under the floor.
 *
 * STILL NOT SEEN (so the browser census in review/audit-d3-focus.mjs remains the measurement): a group
 * that sets neither font-size nor line-height (its box comes from inherited text and children this
 * scan cannot count, e.g. the canvas, sized by script); flex/grid stretch; the inline axis of a
 * text box (its width is its text). These are printed as UNDECIDED, never passed silently as sized. */

/** Pointer-operation handlers: an element carrying one is operated by the pointer. */
const HANDLER_ATTR = /\bon(?:Click|DoubleClick|PointerDown|PointerUp|MouseDown|MouseUp|ContextMenu)\s*=/;

/** Every JSX opening tag in a source, with nested `{…}` expressions (arrow functions included) kept whole. */
function jsxOpeningTags(src: string): string[] {
  const out: string[] = [];
  const re = /<([A-Za-z][\w.]*)(?=[\s/>])/g;
  for (let m = re.exec(src); m !== null; m = re.exec(src)) {
    if (m.index > 0 && /[\w$)\]]/.test(src[m.index - 1]!)) continue; /* a generic or a comparison, not a tag */
    let depth = 0;
    let quote: string | null = null;
    let end = -1;
    for (let i = m.index + m[0].length; i < src.length; i += 1) {
      const ch = src[i]!;
      if (quote !== null) {
        if (ch === "\\") i += 1;
        else if (ch === quote) quote = null;
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") quote = ch;
      else if (ch === "{") depth += 1;
      else if (ch === "}") depth -= 1;
      else if (ch === ">" && depth === 0) {
        end = i;
        break;
      } else if (ch === "<" && depth === 0) break; /* not a tag after all */
    }
    if (end > 0) out.push(src.slice(m.index, end + 1));
  }
  return out;
}

/** The class tokens a `className=…` attribute can produce, one list per string literal in its
 *  expression. Tokens of ONE literal are on the element together; two literals may be alternatives
 *  (`cond ? "a" : "b"`), so they are never read as co-classes. */
function classTokens(tag: string): string[][] {
  const at = tag.search(/\bclassName\s*=/);
  if (at < 0) return [];
  const rest = tag.slice(at).replace(/^className\s*=\s*/, "");
  let expr: string;
  if (rest.startsWith('"')) expr = rest.slice(0, rest.indexOf('"', 1) + 1);
  else if (rest.startsWith("{")) {
    let depth = 0;
    let i = 0;
    for (; i < rest.length; i += 1) {
      if (rest[i] === "{") depth += 1;
      else if (rest[i] === "}" && --depth === 0) break;
    }
    expr = rest.slice(0, i + 1);
  } else return [];
  const out: string[][] = [];
  for (const lit of expr.matchAll(/"([^"]*)"|'([^']*)'|`([^`]*)`/g)) {
    const text = (lit[1] ?? lit[2] ?? lit[3] ?? "").replace(/\$\{[^}]*\}/g, " ");
    const group = text.split(/\s+/).filter((c) => /^[a-z][\w-]*$/i.test(c));
    if (group.length > 0) out.push(group);
  }
  return out;
}

interface Markup {
  /** Classes on an element that carries a pointer handler. */
  operable: Set<string>;
  /** class -> every class the markup puts on the same element with it (itself included). */
  coClasses: Map<string, Set<string>>;
}

function readMarkup(sources: readonly string[]): Markup {
  const operable = new Set<string>();
  const coClasses = new Map<string, Set<string>>();
  for (const src of sources) {
    for (const tag of jsxOpeningTags(src)) {
      const groups = classTokens(tag);
      /* Every alternative is marked operable: over-marking only adds rules to judge. */
      if (HANDLER_ATTR.test(tag)) for (const g of groups) for (const c of g) operable.add(c);
      for (const g of groups) {
        for (const c of g) {
          const set = coClasses.get(c) ?? new Set<string>([c]);
          for (const d of g) set.add(d);
          coClasses.set(c, set);
        }
      }
    }
  }
  return { operable, coClasses };
}

interface StyledRule {
  file: string;
  selector: string;
  body: string;
  /** The classes of each comma-part's SUBJECT compound (the last one), pseudo-elements excluded. */
  subjects: string[][];
}

function styledRules(sheets: readonly Sheet[]): StyledRule[] {
  const out: StyledRule[] = [];
  for (const { file, css: raw } of sheets) {
    const css = raw.replace(/\/\*[\s\S]*?\*\//g, " ");
    for (const block of css.split("}")) {
      const brace = block.lastIndexOf("{");
      if (brace < 0) continue;
      const body = block.slice(brace + 1);
      const selector = block.slice(0, brace).trim().replace(/\s+/g, " ");
      if (selector.startsWith("@") || selector === "") continue;
      const subjects = selector
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "" && !/::?(?:before|after)\b/.test(s))
        .map((s) => {
          /* The subject compound: after the last combinator OUTSIDE parentheses (`:not(.a .b)` stays whole). */
          let depth = 0;
          let cut = 0;
          for (let i = 0; i < s.length; i += 1) {
            const ch = s[i]!;
            if (ch === "(") depth += 1;
            else if (ch === ")") depth -= 1;
            else if (depth === 0 && (ch === " " || ch === ">" || ch === "+" || ch === "~")) cut = i + 1;
          }
          const compound = s.slice(cut).replace(/\([^()]*\)/g, "");
          return [...compound.matchAll(/\.([\w-]+)/g)].map((m) => m[1]!);
        });
      out.push({ file, selector, body, subjects });
    }
  }
  return out;
}

/** The last value of `prop` in a declaration block (the cascade within one rule). */
const decl = (body: string, prop: string): string | undefined => {
  let v: string | undefined;
  for (const m of body.matchAll(new RegExp(`(?:^|[;\\s{])${prop}\\s*:\\s*([^;]+)`, "g"))) v = m[1]!.trim();
  return v;
};

/** Split a CSS value on top-level whitespace (`var(--a) calc(1px + 2px)` is two parts). */
const parts = (v: string): string[] => {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of v.trim()) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (/\s/.test(ch) && depth === 0) {
      if (cur !== "") out.push(cur);
      cur = "";
    } else cur += ch;
  }
  if (cur !== "") out.push(cur);
  return out;
};

/** Padding (or border width) on the two block edges, px; null when a part is not resolvable. */
function blockEdges(body: string, shorthand: "padding" | "border-width", tokens: Map<string, number>): number | null {
  let top: string | undefined;
  let bottom: string | undefined;
  const sh = decl(body, shorthand);
  if (sh !== undefined) {
    const p = parts(sh);
    top = p[0];
    bottom = p[2] ?? p[0];
  }
  const block = decl(body, `${shorthand === "padding" ? "padding" : "border"}-block${shorthand === "padding" ? "" : "-width"}`);
  if (block !== undefined) {
    const p = parts(block);
    top = p[0];
    bottom = p[1] ?? p[0];
  }
  const t = top === undefined ? 0 : top === "0" ? 0 : toPx(top, tokens);
  const b = bottom === undefined ? 0 : bottom === "0" ? 0 : toPx(bottom, tokens);
  return t === null || b === null ? null : t + b;
}

/** The border's block width from `border: 1px solid …` / `border: 0`. */
function borderShorthand(body: string, tokens: Map<string, number>): number {
  const b = decl(body, "border");
  if (b === undefined || b === "0" || b === "none") return 0;
  for (const p of parts(b)) {
    const px = p === "0" ? 0 : toPx(p, tokens);
    if (px !== null) return 2 * px;
  }
  return 0;
}

/** A rule that paints its element as nothing: the visually-hidden recipe's clip. */
const VISUALLY_HIDDEN = /(?:^|[;\s{])clip-path\s*:\s*inset\(\s*50%\s*\)|(?:^|[;\s{])clip\s*:\s*rect\(\s*0/;

interface BoxVerdict {
  rule: string;
  verdict: "declared" | "estimated" | "undecided";
  px?: number;
  detail: string;
}

/**
 * For every target rule: does anything size its element's block axis, and if not, how tall is one
 * line of its own text? `targets` is the rule list the checks above judge; `all` is every rule.
 */
function textBoxVerdicts(
  targets: readonly { file: string; selector: string }[],
  all: readonly StyledRule[],
  markup: Markup,
  tokens: Map<string, number>,
  smallestFont: number,
): BoxVerdict[] {
  const out: BoxVerdict[] = [];
  for (const t of targets) {
    const own = all.find((r) => r.file === t.file && r.selector === t.selector);
    if (own === undefined) continue;
    const classes = new Set<string>();
    for (const subj of own.subjects) for (const c of subj) for (const d of markup.coClasses.get(c) ?? [c]) classes.add(d);
    if (classes.size === 0) {
      out.push({ rule: `${t.file} :: ${t.selector}`, verdict: "undecided", detail: "no class in its subject compound" });
      continue;
    }
    /* Every rule for the same element, the target rule's own first — except a rule that clips the
       element to nothing (the visually-hidden recipe): its 1px box is a state in which there is no
       target to hit, not the size of the target. */
    const group = [
      own,
      ...all.filter((r) => r !== own && !VISUALLY_HIDDEN.test(r.body) && r.subjects.some((s) => s.some((c) => classes.has(c)))),
    ];
    const bodies = group.map((r) => r.body).join(";");
    const declared = [...bodies.matchAll(/(?:^|[;\s{])((?:min-)?(?:height|block-size))\s*:\s*([^;]+)/g)];
    if (declared.length > 0) {
      /* A size another rule of the group declares is judged too: the target rule may carry the cursor
         while a sibling rule carries the size. */
      const px = declared.map((m) => toPx(m[2]!, tokens)).filter((v): v is number => v !== null);
      out.push({
        rule: `${t.file} :: ${t.selector}`,
        verdict: "declared",
        ...(px.length > 0 ? { px: Math.min(...px) } : {}),
        detail: `declared for this element: ${declared.map((m) => `${m[1]} ${m[2]!.trim()}`).join(", ")}`,
      });
      continue;
    }
    const fontDecl = decl(bodies, "font-size");
    const lhDecl = decl(bodies, "line-height");
    if (fontDecl === undefined && lhDecl === undefined) {
      out.push({ rule: `${t.file} :: ${t.selector}`, verdict: "undecided", detail: "sets no size and no text metrics" });
      continue;
    }
    const font = (fontDecl === undefined ? null : toPx(fontDecl, tokens)) ?? smallestFont;
    const lh =
      lhDecl === undefined || lhDecl === "normal"
        ? 1.2 * font
        : /^[\d.]+$/.test(lhDecl)
          ? parseFloat(lhDecl) * font
          : (toPx(lhDecl, tokens) ?? 1.2 * font);
    let pad = 0;
    let border = 0;
    for (const r of group) {
      pad = Math.max(pad, blockEdges(r.body, "padding", tokens) ?? 0);
      border = Math.max(border, borderShorthand(r.body, tokens), blockEdges(r.body, "border-width", tokens) ?? 0);
    }
    const px = Math.round((lh + pad + border) * 100) / 100;
    out.push({
      rule: `${t.file} :: ${t.selector}`,
      verdict: "estimated",
      px,
      detail: `one line ${lh.toFixed(2)} + padding ${pad} + border ${border} (font ${font}px${fontDecl === undefined ? ", the smallest type token" : ""})`,
    });
  }
  return out;
}

const repoSheets = (): Sheet[] =>
  filesUnder(SRC, /\.css$/).map((p) => ({ file: relative(SRC, p).split("\\").join("/"), css: readFileSync(p, "utf8") }));
const repoSources = (): string[] =>
  filesUnder(SRC, /\.tsx$/).filter((p) => !/\.test\.tsx$/.test(p)).map((p) => readFileSync(p, "utf8"));
const repoSeparators = (): Set<string> => separatorClasses(repoSources());

/** Target rules by what the element DOES as well: any rule whose subject carries an operable class. */
function operableRules(sheets: readonly Sheet[], markup: Markup, already: readonly Rule[]): Rule[] {
  const have = new Set(already.map((r) => `${r.file}|${r.selector}`));
  const out: Rule[] = [];
  for (const r of styledRules(sheets)) {
    if (have.has(`${r.file}|${r.selector}`)) continue;
    const hit = r.subjects.flat().find((c) => markup.operable.has(c));
    if (hit !== undefined) out.push({ file: r.file, selector: r.selector, body: r.body, why: `a pointer handler on .${hit}` });
  }
  return out;
}

/** The smallest type token (`--fs-*`), read from tokens.css. */
function smallestTypeToken(tokens: Map<string, number>): number {
  const sizes = [...tokens].filter(([k]) => /^--fs-\d+$/.test(k)).map(([, v]) => v);
  return Math.min(...sizes);
}

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

  describe("targets found by what they DO, and the box a rule leaves to its text (D1/D5, wave 6)", () => {
    const sheets = repoSheets();
    const markup = readMarkup(repoSources());
    const all = styledRules(sheets);
    const smallest = smallestTypeToken(tokens);
    const byHandler = operableRules(sheets, markup, rules);
    const targets = [...rules, ...byHandler];

    it("reads the markup's handler-carrying classes — an empty set would find nothing by behaviour", () => {
      expect(markup.operable.size).toBeGreaterThan(20);
      /* Pinned against the controls this project's markup is known to operate by handler, so a broken
         tag reader (an arrow function's `=>` read as the end of the tag) names what fell out. */
      for (const c of ["fabric3d__btn", "ui-chip__remove", "fabric3d-pointer"]) expect(markup.operable, c).toContain(c);
      expect(smallest).toBe(11);
    });

    it("KNOWN ANSWER: a handler on an element with no role, no tabindex and no cursor makes it a target", () => {
      const m = readMarkup([
        `<span className="p-ptr" data-x="1" onClick={() => scene.current?.focusDevice(d.id)} ref={(el) => { if (el) m.set(id, el); }}>x</span>`,
        `<div className={cond ? "p-a p-b" : \`p-c \${x}\`} onPointerDown={f} />`,
        `<span className="p-inert" title="a > b">no handler</span>`,
        `const r = useRef<HTMLDivElement | null>(null); if (a<b) { <i className="p-after" onClick={g} /> }`,
      ]);
      expect([...m.operable].sort()).toEqual(["p-a", "p-after", "p-b", "p-c", "p-ptr"]);
    });

    it("KNOWN ANSWER: the old `.fabric3d-pointer` shape — operable, no size, one line of 11px text — fails", () => {
      const planted: Sheet[] = [
        {
          file: "planted.css",
          css: `
            .p-oldptr { position: absolute; display: none; gap: var(--sp-1); padding: 1px var(--sp-1);
              font-size: var(--fs-0); line-height: 1.35; cursor: pointer; }
            .p-handler { padding: 2px 0; font-size: var(--fs-1); }
            .p-inherit { cursor: pointer; line-height: 1; padding: var(--sp-1) 0; }
            .p-sized { cursor: pointer; font-size: var(--fs-0); line-height: 1.35; }
            .p-other, .p-sized:hover { min-block-size: var(--target-min); }
            .p-row { block-size: 26px; }
            .p-row--more { cursor: pointer; font-size: var(--fs-1); }
            .p-tall { cursor: pointer; padding: var(--sp-2); font-size: var(--fs-0); line-height: 1.35; border: 1px solid red; }
            .p-canvas[data-hover="true"] { cursor: pointer; }
            .p-split { cursor: pointer; }
            .p-wrap > .p-split, .p-x { block-size: 12px; }
            .p-head { cursor: pointer; min-block-size: var(--target-min); }
            .p-grid .p-head[data-hidden] { block-size: 1px; min-block-size: 0; clip-path: inset(50%); }
          `,
        },
      ];
      const m = readMarkup([`<span className="p-handler" onClick={f}>h</span>`, `<li className="p-row p-row--more" />`]);
      const ts = [...targetRules(planted, new Set()), ...operableRules(planted, m, targetRules(planted, new Set()))];
      const verdicts = textBoxVerdicts(ts, styledRules(planted), m, tokens, smallest);
      const under = verdicts.filter((v) => v.px !== undefined && v.px < FLOOR_PX).map((v) => v.rule.split(" :: ")[1]);
      /* .p-split: the cursor on one rule, an undersized size on a sibling rule for the same element. */
      expect(under.sort()).toEqual([".p-handler", ".p-inherit", ".p-oldptr", ".p-split"]);
      const at = (s: string) => verdicts.find((v) => v.rule.endsWith(`:: ${s}`));
      /* 11 x 1.35 + 2 x 1px = 16.85: the refuter measured 16.84. */
      expect(at(".p-oldptr")?.px).toBeCloseTo(16.85, 1);
      expect(at(".p-sized")?.verdict).toBe("declared");
      expect(at(".p-head")?.px, "a visually-hidden state's 1px clip is not the target's size").toBe(FLOOR_PX);
      expect(at(".p-row--more")?.verdict, "a co-class on the same element sizes it").toBe("declared");
      expect(at(".p-tall")?.verdict).toBe("estimated");
      expect(at(".p-tall")!.px!).toBeGreaterThanOrEqual(FLOOR_PX);
      expect(at('.p-canvas[data-hover="true"]')?.verdict).toBe("undecided");
    });

    it("no operable element's box, left to its own text, can fall under 24px", () => {
      const verdicts = textBoxVerdicts(targets, all, markup, tokens, smallest);
      const under = verdicts.filter((v) => v.px !== undefined && v.px < FLOOR_PX);
      const undecided = verdicts.filter((v) => v.verdict === "undecided");
      /* Printed, never silently passed: the browser census measures these. */
      if (undecided.length > 0) console.info(`target-size: UNDECIDED from source (measured in the browser census):\n  ${undecided.map((v) => `${v.rule} — ${v.detail}`).join("\n  ")}`);
      expect(verdicts.filter((v) => v.verdict !== "undecided").length, "the text-box check judged nothing").toBeGreaterThan(20);
      expect(
        under.map((v) => `${v.rule} :: ${v.px}px = ${v.detail}`),
        `an operable rule that declares no block size is as tall as one line of its text plus its padding.\n` +
          `Under ${FLOOR_PX}px that is an undersized target (acceptance D5): declare a block minimum.`,
      ).toEqual([]);
    });

    it("the handler-found targets declare no size below 24px either", () => {
      expect(byHandler.length, "behaviour found no target the cursor scan had missed").toBeGreaterThan(0);
      expect(offendersIn(byHandler, tokens)).toEqual([]);
    });
  });

  it("no target-size exemption list exists that this scan would be silently ignoring", () => {
    /* design-brief §3.2 names docs/target-size-exceptions.md as the place a genuine spacing exception
       is enumerated. None is needed today. If one is ever written, this scan must be taught to read
       it — until then its existence would be a list of exemptions nothing enforces. */
    expect(existsSync(resolve(SRC, "..", "docs", "target-size-exceptions.md"))).toBe(false);
  });

  it("the brief states why a sub-24px grid cell is not a target, and the code still makes that true", () => {
    /* The D5 browser census finds `div.ag__cell` boxes under 24px (one line of text in a >= 32px row).
       They are not spacing exceptions: the ROW is the target. That argument lived only in D5's grade;
       design-brief §3.2 now carries it, and requires the exceptions file only when a spacing exception
       exists. The argument is only as true as the code it cites, so the code is read here too. */
    const brief = readFileSync(resolve(SRC, "..", "docs", "design-brief.md"), "utf8");
    const s32 = brief.slice(brief.indexOf("### 3.2 "), brief.indexOf("### 3.3 ")).replace(/\s+/g, " ");
    expect(s32, "design-brief §3.2 not found").toContain("hit targets");
    expect(s32).toContain("A grid cell is part of its row's target, not a target of its own");
    expect(s32).toContain("`docs/target-size-exceptions.md` exists only while at least one such exception does");
    const s7 = brief.slice(brief.indexOf("| **2.5.8** Target Size")).split("\n")[0]!;
    expect(s7).toContain("none exists today");

    const grid = readFileSync(join(SRC, "panels", "DataGrid.tsx"), "utf8").replace(/\s+/g, " ");
    // the data row activates; a cell only moves the roving focus, and stops the click only when it
    // holds its own control (which is then a target in its own right, under the 24px floor above)
    expect(grid).toMatch(/onClick=\{\(e\) => \{ const inCell =[^}]*?handlers\.activate\(node\.item/);
    expect(grid).toMatch(/onClick=\{\(e\) => \{ handlers\.move\(r, c\);[^}]*?if \(col\.interactive\) e\.stopPropagation\(\); \}\}/);
    const gridCss = readFileSync(join(SRC, "panels", "DataGrid.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(gridCss).toMatch(/\.ag__row--data \{[^}]*cursor: default;/);
    const cellRules = [...gridCss.matchAll(/(^|\})\s*([^{}]*\.ag__cell[^{}]*)\{([^}]*)\}/g)].filter((m) => /cursor\s*:/.test(m[3]!));
    expect(
      cellRules.map((m) => m[2]!.trim()),
      "a cell rule declares a cursor, presenting the cell as a control of its own",
    ).toEqual([]);
  });
});
