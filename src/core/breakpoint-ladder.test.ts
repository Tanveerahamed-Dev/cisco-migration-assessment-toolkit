/**
 * breakpoint-ladder.test.ts — the viewport ladder tiles the width line: no gap, no overlap, at
 * FRACTIONAL widths as well as whole ones (acceptance F4 regression, repair wave 8).
 *
 * THE DEFECT. Every rung of the ladder was written as TWO numbers: the narrow side as
 * `(max-width: 47.9375rem)` (767 px) and the wide side as `(min-width: 48rem)` (768 px). A media
 * width is a CSS-pixel length, not an integer: under Windows 125/150/175 % scaling a window can
 * report 767.349 px, which matches NEITHER rule. Measured by the independent refuter at
 * `--force-device-scale-factor=1.5 --window-size=781,900`: mediaWidth 767.3490, `le767` false,
 * `ge768` false, so `useLadder` said "not stacked", App seeded the fabric visible and the three.js
 * chunk was fetched at 985 ms on a viewport the brief collapses — and the stylesheets, in no rung
 * at all, overlapped the Finding/Device controls with the first grid row and clipped the status
 * bar. The same split sat at 1023-1024 and 1279-1280, and `(max-width: 48rem)` in
 * PriorityQueue.css OVERLAPPED the `(min-width: 48rem)` rung at exactly 768 px. Every earlier F4
 * probe used integer widths only, which is exactly the one set of widths the defect cannot reach.
 *
 * THE RULE held here. `LADDER_REM` in `src/app/surfaces.tsx` is the ONE owner of the ladder's
 * boundaries. Its rungs are the half-open intervals between consecutive boundaries, so they
 * partition [0, inf) by construction. Then:
 *
 *   1. every width condition in every stylesheet under src/ (and every HTML page at the root) is a
 *      UNION OF RUNGS — its answer is constant on each rung, sampled every 0.05 px from 300 to
 *      2000 and at every boundary +/- 0.01, 0.5 and 0.99 px. A `max-width` one sixteenth of a rem
 *      below a boundary fails on the gap; a `max-width` AT a boundary fails on the overlap;
 *   2. every width query string in the application's TypeScript is either the owner's own
 *      `(min-width: ${rem}rem)` builder or a literal that is itself a union of rungs;
 *   3. `useLadder` answers from the owner's queries and lands every sampled width, fractional or
 *      not, in exactly the rung the owner assigns it;
 *   4. every owner boundary is a real edge of at least one stylesheet rule, so the CSS ladder and
 *      the JS ladder have the same rungs rather than two lists that happen to agree today.
 *
 * The evaluator below answers `min-width` as `>=` and `max-width` as `<=` on a real-valued width,
 * which is what a browser does. It models only the syntax this app uses and THROWS on anything
 * else (an `or`, a nested condition, `device-width`, an unknown unit), so an unmodelled shape is
 * reported as a violation instead of being skipped.
 *
 * NOT IN SCOPE: `@container` queries (PathTrace.css). They measure a container's inline size, a
 * different line from the viewport's, and the viewport ladder does not apply to them.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import ts from "typescript";
import { afterEach, describe, expect, it } from "vitest";

import { LADDER_REM, atLeast, useLadder, type Ladder } from "../app/surfaces";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = join(ROOT, "src");

/* ══ the owner's rungs ═══════════════════════════════════════════════════════════════════════════ */

/** One rem in a media query is the initial font size, 16 CSS px, whatever the page's own root size. */
const REM_PX = 16;
const BOUNDS = Object.values(LADDER_REM)
  .map((rem) => rem * REM_PX)
  .sort((a, b) => a - b);

/** Which rung `w` is in: the number of boundaries at or below it (a rung includes its lower edge). */
const rungOf = (w: number, bounds: readonly number[] = BOUNDS): number => bounds.filter((b) => b <= w).length;
/** A width well inside rung `i`, far from both of its edges. */
function repOf(i: number, bounds: readonly number[] = BOUNDS): number {
  const lo = i === 0 ? 0 : (bounds[i - 1] as number);
  const hi = i === bounds.length ? (bounds[bounds.length - 1] as number) + 400 : (bounds[i] as number);
  return (lo + hi) / 2;
}

/** The measured widths that reached the gap, named so they are sampled whatever the sweep's step. */
const MEASURED = [767.349, 767.44, 1023.5, 1279.5];
const OFFSETS = [-0.99, -0.5, -0.01, 0, 0.01, 0.5, 0.99];
function samplesFor(bounds: readonly number[]): number[] {
  const out: number[] = [...MEASURED];
  for (const b of bounds) for (const d of OFFSETS) out.push(Math.round((b + d) * 1000) / 1000);
  for (let i = 0; i <= (2000 - 300) * 20; i += 1) out.push(300 + i / 20);
  return [...new Set(out)];
}
const SAMPLES = samplesFor(BOUNDS);

/* ══ a media-query evaluator for the syntax this app uses, and nothing else ════════════════════ */

type WidthPred = (w: number) => boolean;
/** `null`: the query has no width condition, or never applies to a screen (print). */
type Parsed = WidthPred | null;

const UNIT: Readonly<Record<string, number>> = { px: 1, rem: REM_PX, em: REM_PX };

function lengthPx(v: string): number {
  const m = /^(\d+(?:\.\d+)?|\.\d+)(px|rem|em)$/.exec(v.trim());
  if (!m) throw new Error(`unmodelled length "${v}"`);
  return Number(m[1]) * (UNIT[m[2] as string] as number);
}

const cmp = (a: number, op: string, b: number): boolean =>
  op === "<" ? a < b : op === "<=" ? a <= b : op === ">" ? a > b : op === ">=" ? a >= b : a === b;

/** One parenthesised feature: a width predicate, or "other" for a non-width feature. */
function feature(inner: string): WidthPred | "other" {
  const s = inner.trim();
  let m = /^(min|max)-width\s*:\s*(\S+)$/.exec(s);
  if (m) {
    const b = lengthPx(m[2] as string);
    return m[1] === "min" ? (w) => w >= b : (w) => w <= b;
  }
  m = /^width\s*(<=|>=|<|>|=)\s*(\S+)$/.exec(s);
  if (m) {
    const [op, b] = [m[1] as string, lengthPx(m[2] as string)];
    return (w) => cmp(w, op, b);
  }
  m = /^(\S+)\s*(<=|>=|<|>|=)\s*width$/.exec(s);
  if (m) {
    const [b, op] = [lengthPx(m[1] as string), m[2] as string];
    return (w) => cmp(b, op, w);
  }
  m = /^(\S+)\s*(<=|<)\s*width\s*(<=|<)\s*(\S+)$/.exec(s);
  if (m) {
    const [lo, op1, op2, hi] = [lengthPx(m[1] as string), m[2] as string, m[3] as string, lengthPx(m[4] as string)];
    return (w) => cmp(lo, op1, w) && cmp(w, op2, hi);
  }
  if (/width/.test(s)) throw new Error(`unmodelled width feature "(${s})"`);
  if (/^\(|^not\b|\b(and|or)\b/.test(s)) throw new Error(`unmodelled nested condition "(${s})"`);
  return "other";
}

/** ONE media query (no top-level comma). Throws on any shape this evaluator does not model. */
function parseQuery(query: string): Parsed {
  let s = query.trim().toLowerCase().replace(/\s+/g, " ");
  let negate = false;
  let type = "all";
  let m = /^(not|only) /.exec(s);
  if (m) {
    negate = m[1] === "not";
    s = s.slice(m[0].length);
  }
  m = /^(all|screen|print)\b ?/.exec(s);
  if (m) {
    type = m[1] as string;
    s = s.slice(m[0].length);
    if (s !== "") {
      const and = /^and /.exec(s);
      if (!and) throw new Error(`unmodelled query "${query}"`);
      s = s.slice(and[0].length);
    }
  } else if (negate) {
    throw new Error(`unmodelled query "${query}": MQ4 \`not (...)\` without a media type`);
  }
  const preds: WidthPred[] = [];
  let others = 0;
  while (s !== "") {
    if (s[0] !== "(") throw new Error(`unmodelled query "${query}"`);
    let depth = 0;
    let end = -1;
    for (let i = 0; i < s.length; i += 1) {
      if (s[i] === "(") depth += 1;
      else if (s[i] === ")" && --depth === 0) {
        end = i;
        break;
      }
    }
    if (end < 0) throw new Error(`unbalanced query "${query}"`);
    const f = feature(s.slice(1, end));
    if (f === "other") others += 1;
    else preds.push(f);
    s = s.slice(end + 1).trim();
    if (s === "") break;
    const and = /^and /.exec(s);
    if (!and) throw new Error(`unmodelled combinator in "${query}" (only \`and\` is modelled)`);
    s = s.slice(and[0].length);
  }
  if (type === "print") {
    if (negate) throw new Error(`unmodelled query "${query}"`);
    return null;
  }
  if (preds.length === 0) return null;
  if (negate && others > 0) throw new Error(`unmodelled query "${query}": \`not\` over width and non-width features at once`);
  const all: WidthPred = (w) => preds.every((p) => p(w));
  return negate ? (w) => !all(w) : all;
}

/** Split a media query list at its top-level commas. */
const queriesOf = (list: string): string[] => {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of list) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out.map((q) => q.trim()).filter((q) => q !== "");
};

/** Violations of "a union of rungs" for one media query list, located at `where`. */
function checkList(where: string, list: string, bounds: readonly number[] = BOUNDS, samples: readonly number[] = SAMPLES): string[] {
  const out: string[] = [];
  for (const q of queriesOf(list)) {
    let p: Parsed;
    try {
      p = parseQuery(q);
    } catch (e) {
      out.push(`${where} ${q}: ${(e as Error).message}`);
      continue;
    }
    if (p === null) continue;
    const off = samples.filter((w) => p(w) !== p(repOf(rungOf(w, bounds), bounds)));
    if (off.length > 0) {
      const shown = off.slice(0, 4).map((w) => `${w}px ${p(w) ? "matches" : "does not match"}`);
      out.push(`${where} ${q}: not a union of ladder rungs — ${shown.join(", ")} (${off.length} sample(s)), unlike the rest of its rung`);
    }
  }
  return out;
}

/* ══ the stylesheets ═════════════════════════════════════════════════════════════════════════════ */

function walk(dir: string, keep: (f: string) => boolean): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = join(dir, d.name);
    return d.isDirectory() ? walk(p, keep) : keep(p) ? [p] : [];
  });
}

const blankComments = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
const lineAt = (text: string, index: number): number => text.slice(0, index).split("\n").length;

/** Every `@media` prelude in a stylesheet, with where it is. */
function mediaPreludes(file: string, css: string): { where: string; list: string }[] {
  const clean = blankComments(css);
  return [...clean.matchAll(/@media\s+([^{;]+)\{/g)].map((m) => ({ where: `${file}:${lineAt(clean, m.index)}`, list: (m[1] as string).trim() }));
}

/** Every media list in an HTML page: its <style> blocks, and every `media="..."` attribute. */
function htmlPreludes(file: string, html: string): { where: string; list: string }[] {
  const out: { where: string; list: string }[] = [];
  for (const m of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) out.push(...mediaPreludes(file, m[1] as string));
  for (const m of html.matchAll(/\bmedia\s*=\s*"([^"]*)"/gi)) out.push({ where: `${file}:${lineAt(html, m.index)}`, list: m[1] as string });
  return out;
}

const CSS_FILES = walk(SRC, (f) => f.endsWith(".css"));
const HTML_FILES = readdirSync(ROOT).filter((f) => f.endsWith(".html"));
const PRELUDES = [
  ...CSS_FILES.flatMap((f) => mediaPreludes(relative(ROOT, f).replace(/\\/g, "/"), readFileSync(f, "utf8"))),
  ...HTML_FILES.flatMap((f) => htmlPreludes(f, readFileSync(join(ROOT, f), "utf8"))),
];

/* ══ the TypeScript ══════════════════════════════════════════════════════════════════════════════ */

const WIDTH_FEATURE = /\(\s*(?:[\d.]+[a-z]*\s*[<>]=?\s*)?(?:(?:min|max)-)?(?:device-)?width\s*(?::|[<>]=?|=)/;
/** The owner's builder, as its template literal reads with the substitution elided. */
const OWNER_TEMPLATE = "(min-width: ${}rem)";
const OWNER_FILE = "src/app/surfaces.tsx";

type Literal = { where: string; text: string; template: boolean };

/** Every string and template literal in `code` that carries a width media feature. */
function widthLiterals(file: string, code: string): Literal[] {
  const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: Literal[] = [];
  const visit = (n: ts.Node): void => {
    let text: string | null = null;
    let template = false;
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) text = n.text;
    else if (ts.isTemplateExpression(n)) {
      text = n.head.text + n.templateSpans.map((s) => "${}" + s.literal.text).join("");
      template = true;
    }
    if (text !== null && WIDTH_FEATURE.test(text)) {
      out.push({ where: `${file}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}`, text, template });
    }
    if (!ts.isTemplateExpression(n)) ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

function checkLiterals(file: string, lits: readonly Literal[]): string[] {
  return lits.flatMap((l) => {
    if (!l.template) return checkList(l.where, l.text);
    if (l.text === OWNER_TEMPLATE && file === OWNER_FILE) return [];
    return [`${l.where} \`${l.text}\`: a width query built at runtime outside the ladder's owner (${OWNER_FILE}) cannot be proved to tile the line`];
  });
}

const TS_FILES = walk(SRC, (f) => /\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f) && !f.endsWith(".d.ts"));
const LITERALS = TS_FILES.map((f) => {
  const rel = relative(ROOT, f).replace(/\\/g, "/");
  return { file: rel, lits: widthLiterals(rel, readFileSync(f, "utf8")) };
});

/* ══ the live hook, under a matchMedia that evaluates the real query at a real-valued width ════ */

const mountedRoots: (() => void)[] = [];
afterEach(() => {
  for (const u of mountedRoots.splice(0)) u();
});

function probeLadder(widths: readonly number[]): { asked: Set<string>; wrong: string[] } {
  const real = window.matchMedia;
  let width = widths[0] ?? 0;
  const asked = new Set<string>();
  window.matchMedia = ((q: string) => {
    asked.add(q);
    const p = queriesOf(q).map(parseQuery);
    const matches = p.some((x) => x !== null && x(width));
    return {
      matches,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;
  let seen: Ladder | null = null;
  function Probe(): null {
    seen = useLadder();
    return null;
  }
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mountedRoots.push(() => {
    act(() => root.unmount());
    host.remove();
    window.matchMedia = real;
  });
  const NAMES = ["stacked", "singleColumn", "drawer", "reference"] as const;
  const wrong: string[] = [];
  act(() => root.render(createElement(Probe)));
  for (const w of widths) {
    width = w;
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    const l = seen as Ladder | null;
    if (l === null) throw new Error("the probe never rendered");
    const on = [l.stacked, l.singleColumn, l.drawer, !l.stacked && !l.singleColumn && !l.drawer];
    const want = Math.min(rungOf(w), 3);
    const got = on.flatMap((v, i) => (v ? [NAMES[i]] : []));
    if (got.length !== 1 || !on[want]) wrong.push(`${w}px: useLadder says [${got.join(", ")}], the owner's rung is ${NAMES[want]}`);
  }
  return { asked, wrong };
}

/* ══ the gate ════════════════════════════════════════════════════════════════════════════════════ */

describe("the viewport ladder tiles the width line (F4, fractional widths)", () => {
  it("finds what it guards: the owner, the stylesheets' width rules and the TypeScript's width queries", () => {
    expect(BOUNDS.length).toBeGreaterThanOrEqual(3);
    expect(CSS_FILES.length).toBeGreaterThan(5);
    const widthRules = PRELUDES.filter((p) => /width/.test(p.list));
    expect(widthRules.length, "no width-conditioned @media rule found at all").toBeGreaterThan(5);
    const owner = LITERALS.find((l) => l.file === OWNER_FILE)?.lits ?? [];
    expect(owner.map((l) => l.text), "the owner's own query builder was not found by the scan").toContain(OWNER_TEMPLATE);
    expect(atLeast(LADDER_REM.singleColumn)).toBe("(min-width: 48rem)");
  });

  it("every width condition in every stylesheet is a union of the owner's rungs", () => {
    expect(PRELUDES.flatMap((p) => (/width/.test(p.list) ? checkList(p.where, p.list) : []))).toEqual([]);
  });

  it("every width query in the application's TypeScript is the owner's builder or a union of its rungs", () => {
    expect(LITERALS.flatMap((l) => checkLiterals(l.file, l.lits))).toEqual([]);
  });

  it("every owner boundary is an edge of some stylesheet rule, so the CSS ladder has the JS ladder's rungs", () => {
    const preds = PRELUDES.flatMap((p) => queriesOf(p.list).map(parseQuery)).filter((p): p is WidthPred => p !== null);
    const unused = BOUNDS.filter((b) => !preds.some((p) => p(b - 0.01) !== p(b)));
    expect(unused, "an owner boundary no stylesheet rule changes at").toEqual([]);
  });

  it("useLadder asks only the owner's queries and puts every sampled width in exactly the owner's rung", () => {
    /* Every boundary at the stated offsets, the measured widths, and a sweep every 0.25 px: the
       hook's answer can only change where one of its three queries does, so this is exhaustive
       for the queries it asks — which the first assertion pins to the owner's. */
    const widths = [...MEASURED, ...BOUNDS.flatMap((b) => OFFSETS.map((d) => b + d))];
    for (let w = 300; w <= 2000; w += 0.25) widths.push(w);
    const { asked, wrong } = probeLadder(widths);
    const owner = new Set(Object.values(LADDER_REM).map(atLeast));
    expect([...asked].filter((q) => !owner.has(q)), "useLadder asked a width query the owner does not define").toEqual([]);
    expect(asked.size).toBeGreaterThanOrEqual(3);
    expect(wrong).toEqual([]);
  });
});

describe("the detectors fire on the shapes they exist for (positive controls)", () => {
  it("the gap: a max-width 1/16 rem below a min-width boundary fails at 767.349 and 767.44", () => {
    const bad = checkList("planted.css:1", "(max-width: 47.9375rem)");
    expect(bad.length).toBe(1);
    expect(bad[0]).toMatch(/767\.349px does not match/);
    const css = "@media (max-width: 47.9375rem) { a { b: c } }\n@media (min-width: 48rem) { a { b: d } }";
    const found = mediaPreludes("planted.css", css).flatMap((p) => checkList(p.where, p.list));
    expect(found.length).toBe(1);
    expect(found[0]).toMatch(/^planted\.css:1 /);
  });

  it("the overlap: a max-width AT a boundary fails at exactly that width", () => {
    const bad = checkList("planted.css:1", "(max-width: 48rem)");
    expect(bad.length).toBe(1);
    expect(bad[0]).toMatch(/768px matches/);
  });

  it("the complement is clean: `not all and (min-width: X)` and `(width < X)` tile with `(min-width: X)`", () => {
    expect(checkList("p", "not all and (min-width: 48rem)")).toEqual([]);
    expect(checkList("p", "(width < 64rem)")).toEqual([]);
    expect(checkList("p", "(48rem <= width < 64rem)")).toEqual([]);
    expect(checkList("p", "(min-width: 48rem) and (prefers-reduced-motion: reduce)")).toEqual([]);
    expect(checkList("p", "print")).toEqual([]);
  });

  it("a boundary the owner does not declare fails, and an unmodelled shape is reported rather than skipped", () => {
    expect(checkList("p", "(min-width: 50rem)").length).toBe(1);
    expect(checkList("p", "(min-width: 48rem) or (hover: hover)")[0]).toMatch(/unmodelled combinator/);
    expect(checkList("p", "(min-device-width: 48rem)")[0]).toMatch(/unmodelled width feature/);
    expect(checkList("p", "not (min-width: 48rem)")[0]).toMatch(/unmodelled query/);
    expect(checkList("p", "(min-width: 48vw)")[0]).toMatch(/unmodelled length/);
  });

  it("the TypeScript scan flags a gap literal and a width query built outside the owner", () => {
    const code =
      'const a = useMediaQuery("(max-width: 47.9375rem)");\n' +
      "const b = matchMedia(`(max-width: ${x}rem)`);\n" +
      'const c = "(min-width: 64rem)";\n' +
      "// (max-width: 47.9375rem) in a comment is not a query\n";
    const lits = widthLiterals("src/app/planted.tsx", code);
    expect(lits.map((l) => l.text)).toEqual(["(max-width: 47.9375rem)", "(max-width: ${}rem)", "(min-width: 64rem)"]);
    const bad = checkLiterals("src/app/planted.tsx", lits);
    expect(bad.length).toBe(2);
    expect(bad[0]).toMatch(/planted\.tsx:1 .*767\.349px does not match/);
    expect(bad[1]).toMatch(/planted\.tsx:2 .*built at runtime outside the ladder's owner/);
  });

  it("the hook probe reports a ladder whose rungs leave a gap (the pre-wave-8 queries)", () => {
    /* The hook under test is the real one; this control drives the probe's own judgement with the
       old two-number queries, evaluated at the measured width, to show it would have said so. */
    const oldStacked = parseQuery("(max-width: 47.9375rem)") as WidthPred;
    const oldSingle = parseQuery("(min-width: 48rem) and (max-width: 63.9375rem)") as WidthPred;
    const w = 767.349;
    expect([oldStacked(w), oldSingle(w)]).toEqual([false, false]);
    expect(rungOf(w)).toBe(0);
  });
});
