/**
 * motion-inventory.test.ts — design brief §4.8 lists every animation the code declares, with the
 * duration the code gives it, and lists nothing the code does not have (C6).
 *
 * HISTORY. The acceptance report (C6) first found §4.8 omitting two animations; the fix discovered
 * `@keyframes` and script `*_MS` transitions. An independent refuter (wave 3) then found the table
 * still false against the code in both directions: it claimed a trace draw-on "staggered 18 ms per
 * hop" (flow.ts has one 240 ms reveal and no stagger) and a "Command palette 140 ms" that exists
 * nowhere (the palette's only motion is its rows' 80 ms hover tint), and it omitted the skip-link,
 * stage-dim, drawer, switch, chevron, label and progress transitions — because this test never read
 * a CSS `transition:` declaration at all. The keyframes loop it did run iterated over an empty list
 * and asserted nothing (the runtime assertion guard, src/test-setup.ts, now fails that shape).
 *
 * WHAT IS DISCOVERED, from the code, not from a list:
 *   CSS  every `transition`, `transition-duration`, `animation` and `animation-duration` declaration in
 *        every stylesheet under src/ (and every `<style>` in a root HTML page), with each duration and
 *        delay RESOLVED through the `--dur-*` tokens in src/core/tokens.css, keyed by its selector.
 *        Declarations inside `@media (prefers-reduced-motion: reduce)` are the collapse, not motion:
 *        they are held to <= 1 ms instead.
 *   JS   every `*_MS` constant that is the DIVISOR of a progress fraction (`(now - start) / X_MS`,
 *        `elapsed / X_MS`) or is interpolated into an inline `transition`/`animation`; every ease the
 *        ease owner exports; every OrbitControls `dampingFactor`. And any inline `transition` or
 *        `animation` a script sets in a form this scan cannot resolve fails, so a new spelling
 *        cannot hide.
 *
 * WHAT IS REQUIRED of §4.8's table, both directions:
 *   forward  each discovered item is named in backticks in the first cell of a row whose Duration
 *            cell states each of its resolved times as **N ms**, its properties, and its token; whose
 *            Easing cell names its timing functions; and which states its reduced-motion behaviour.
 *   reverse  every row names at least one discovered item, every backticked name in its first cell
 *            exists in the source, and every time in its Duration cell (bold or not) is a time the
 *            code actually has for what that row names — so "staggered 18 ms per hop" and a
 *            "Command palette 140 ms" both fail.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { EASES, createEaseChannel, stepEaseChannel } from "../fabric3d/emphasis";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = resolve(PKG, "src");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const files = walk(SRC).filter((f) => !/\.test\.tsx?$/.test(f));
const rel = (f: string) => relative(PKG, f).split("\\").join("/");

const brief = readFileSync(resolve(PKG, "docs", "design-brief.md"), "utf8");
const s48 = (() => {
  const a = brief.indexOf("### 4.8 ");
  const b = brief.indexOf("### 4.9 ", a);
  expect(a, "design brief §4.8 exists").toBeGreaterThanOrEqual(0);
  return brief.slice(a, b < 0 ? undefined : b);
})();

/* ── CSS: a small declaration parser ────────────────────────────────────────────────────────────── */

interface CssDecl {
  file: string;
  line: number;
  selector: string;
  atRules: string[];
  prop: string;
  value: string;
}

/** Every declaration in a stylesheet, with its selector and enclosing at-rules. Comments are blanked
 *  (newlines kept, so line numbers hold) and quoted strings are skipped over when splitting. */
export function cssDeclarations(file: string, css: string): CssDecl[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  const out: CssDecl[] = [];
  const stack: string[] = [];
  let buf = "";
  let bufAt = 0;
  const lineAt = (i: number): number => text.slice(0, i).split("\n").length;
  const flush = (): void => {
    const raw = buf.trim();
    buf = "";
    const colon = raw.indexOf(":");
    if (raw === "" || colon < 0) return;
    const selector = [...stack].reverse().find((s) => !s.startsWith("@")) ?? "";
    out.push({
      file,
      line: lineAt(bufAt),
      selector: selector.replace(/\s+/g, " "),
      atRules: stack.filter((s) => s.startsWith("@")).map((s) => s.replace(/\s+/g, " ")),
      prop: raw.slice(0, colon).trim().toLowerCase(),
      value: raw.slice(colon + 1).trim().replace(/\s+/g, " ").replace(/\s*!important$/, ""),
    });
  };
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i]!;
    if (c === '"' || c === "'") {
      const end = text.indexOf(c, i + 1);
      buf += text.slice(i, end < 0 ? undefined : end + 1);
      i = end < 0 ? text.length : end;
      continue;
    }
    if (buf.trim() === "") bufAt = i;
    if (c === "{") {
      stack.push(buf.trim());
      buf = "";
    } else if (c === "}") {
      flush();
      stack.pop();
    } else if (c === ";") {
      flush();
    } else {
      buf += c;
    }
  }
  return out;
}

/** Split at top-level commas / whitespace (not inside parentheses). */
function splitTop(s: string, sep: "," | " "): string[] {
  const parts: string[] = [];
  let depth = 0;
  let cur = "";
  for (const c of s) {
    if (c === "(") depth += 1;
    if (c === ")") depth -= 1;
    if (depth === 0 && (sep === "," ? c === "," : /\s/.test(c))) {
      if (cur.trim() !== "") parts.push(cur.trim());
      cur = "";
    } else cur += c;
  }
  if (cur.trim() !== "") parts.push(cur.trim());
  return parts;
}

const TOKENS_CSS = resolve(SRC, "core", "tokens.css");
const isReducedMotion = (atRules: readonly string[]): boolean => atRules.some((a) => /prefers-reduced-motion:\s*reduce/.test(a));

/** The motion tokens (`--dur-*`, `--ease-*`) as the default (full-motion) theme declares them. */
function motionTokens(): Map<string, string> {
  const tokens = new Map<string, string>();
  for (const d of cssDeclarations("src/core/tokens.css", readFileSync(TOKENS_CSS, "utf8"))) {
    if (!/^--(dur|ease)-/.test(d.prop) || isReducedMotion(d.atRules)) continue;
    const prior = tokens.get(d.prop);
    expect(prior === undefined || prior === d.value, `${d.prop} is declared twice outside reduced motion with different values`).toBe(true);
    tokens.set(d.prop, d.value);
  }
  return tokens;
}
const TOKENS = motionTokens();

/** A CSS time in ms, or null when the token is not a time. */
function timeMs(tok: string): number | null {
  const m = /^(-?\d*\.?\d+)(ms|s)$/.exec(tok);
  return m === null ? null : Number(m[1]) * (m[2] === "s" ? 1000 : 1);
}

interface CssMotion {
  file: string;
  line: number;
  selector: string;
  atRules: string[];
  kind: "transition" | "animation";
  /** Transitioned properties, or the animation's keyframes name. */
  subjects: string[];
  /** Every duration and delay, resolved, in ms. */
  times: number[];
  /** Per comma-separated item, the moment it reaches its end state: delay + duration. */
  ends: number[];
  /** Tokens the times were read through, e.g. `--dur-instant`. */
  tokens: string[];
  /** Timing functions as written (`linear`, `--ease-out`, `ease-in-out`, `cubic-bezier(…)`). */
  easings: string[];
  /** Any time given as a literal rather than through a `--dur-*` token (it would not collapse under
   *  reduced motion). */
  literalTimes: number[];
  infinite: boolean;
}

const EASING_KEYWORDS = /^(linear|ease|ease-in|ease-out|ease-in-out|step-start|step-end)$/;
const ANIMATION_KEYWORDS = /^(infinite|normal|reverse|alternate|alternate-reverse|none|forwards|backwards|both|running|paused)$/;

/** Every motion declaration in one stylesheet, times resolved through the motion tokens. */
export function cssMotionIn(file: string, css: string, tokens: ReadonlyMap<string, string> = TOKENS): CssMotion[] {
  const out: CssMotion[] = [];
  for (const d of cssDeclarations(file, css)) {
    const m = /^(transition|animation)(-duration|-delay)?$/.exec(d.prop);
    if (m === null) continue;
    const kind = m[1] as "transition" | "animation";
    const motion: CssMotion = { file, line: d.line, selector: d.selector, atRules: d.atRules, kind, subjects: [], times: [], ends: [], tokens: [], easings: [], literalTimes: [], infinite: false };
    for (const item of splitTop(d.value, ",")) {
      const before = motion.times.length;
      for (const tok of splitTop(item, " ")) {
        const v = /^var\((--[\w-]+)(?:,\s*(.+))?\)$/.exec(tok);
        if (v !== null) {
          const resolved = tokens.get(v[1]!) ?? v[2]?.trim();
          expect(resolved, `${file}:${d.line} ${v[1]} is not a motion token`).toBeDefined();
          const t = timeMs(resolved!);
          if (t !== null) {
            motion.times.push(t);
            motion.tokens.push(v[1]!);
          } else motion.easings.push(v[1]!);
          continue;
        }
        const t = timeMs(tok);
        if (t !== null) {
          motion.times.push(t);
          if (t !== 0) motion.literalTimes.push(t);
        } else if (EASING_KEYWORDS.test(tok) || /^(cubic-bezier|steps)\(/.test(tok)) motion.easings.push(tok);
        else if (tok === "infinite") motion.infinite = true;
        else if (/^\d+$/.test(tok) || ANIMATION_KEYWORDS.test(tok)) continue;
        else if (m[2] === undefined) motion.subjects.push(tok);
      }
      // CSS: the first time in an item is its duration, the second its delay.
      const own = motion.times.slice(before);
      motion.ends.push((own[0] ?? 0) + (own[1] ?? 0));
    }
    out.push(motion);
  }
  return out;
}

/** Every `@keyframes` name one stylesheet declares (vendor-prefixed spellings included). Its own
 *  known-answer case below must find planted names, so a regex that loses its escapes (the wave-3
 *  `/@(?:-[a-z]+-)?keyframess+([w-]+)/g`, which matched nothing) turns the suite red instead of passing vacuously. */
export function keyframeNamesIn(css: string): string[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, " ");
  return [...text.matchAll(/@(?:-[a-z]+-)?keyframes\s+([\w-]+)/g)].map((k) => k[1]!);
}

/** The stylesheets the product ships: every .css under src/, plus `<style>` blocks in root pages. */
const stylesheets = files.filter((f) => f.endsWith(".css"));
const htmlStyles = readdirSync(PKG)
  .filter((n) => n.endsWith(".html"))
  .flatMap((n) => [...readFileSync(resolve(PKG, n), "utf8").matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => ({ file: n, css: m[1]! })));
const allCssMotion = [
  ...stylesheets.flatMap((f) => cssMotionIn(rel(f), readFileSync(f, "utf8"))),
  ...htmlStyles.flatMap((h) => cssMotionIn(h.file, h.css)),
];
/** Motion, as opposed to the reduced-motion collapse of it. */
const cssMotion = allCssMotion.filter((m) => !isReducedMotion(m.atRules));
const cssCollapse = allCssMotion.filter((m) => isReducedMotion(m.atRules));

/* ── JS: progress divisors, inline transitions, eases, damping ─────────────────────────────────── */

interface ScriptMotion {
  file: string;
  line: number;
  name: string;
  kind: "progress" | "inline-css" | "ease" | "damping";
  /** The constant's value: ms for a duration, a per-frame factor for damping. */
  value: number | undefined;
}

/** Every animation-timing constant one script declares, found by what the code DOES with it. */
export function scriptMotionIn(file: string, text: string): { found: ScriptMotion[]; unresolved: string[] } {
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const consts = new Map<string, number>();
  const found: ScriptMotion[] = [];
  const unresolved: string[] = [];
  const lineOf = (n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
  const collect = (n: ts.Node): void => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined && ts.isNumericLiteral(n.initializer)) {
      consts.set(n.name.text, Number(n.initializer.text));
    }
    ts.forEachChild(n, collect);
  };
  collect(sf);
  const strip = (e: ts.Expression): ts.Expression => {
    let x = e;
    while (ts.isParenthesizedExpression(x) || ts.isAsExpression(x) || ts.isNonNullExpression(x)) x = x.expression;
    return x;
  };
  const MOTION_PROP = /^(transition|animation|transitionDuration|animationDuration|transitionDelay|animationDelay)$/;
  const visit = (n: ts.Node): void => {
    // A progress fraction: `something / X_MS`.
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.SlashToken) {
      const r = strip(n.right);
      if (ts.isIdentifier(r) && /^[A-Z][A-Z0-9_]*_MS$/.test(r.text)) {
        found.push({ file, line: lineOf(n), name: r.text, kind: "progress", value: consts.get(r.text) });
      }
    }
    // An inline CSS motion property set from script: `el.style.transition = …` or `{ transition: … }`.
    const setsMotion =
      (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isPropertyAccessExpression(n.left) && MOTION_PROP.test(n.left.name.text)) ||
      (ts.isPropertyAssignment(n) && (ts.isIdentifier(n.name) || ts.isStringLiteral(n.name)) && MOTION_PROP.test(n.name.text));
    if (setsMotion) {
      const value = ts.isBinaryExpression(n) ? n.right : (n as ts.PropertyAssignment).initializer;
      const names = ts.isTemplateExpression(value)
        ? value.templateSpans.map((s) => strip(s.expression)).filter(ts.isIdentifier).map((i) => i.text).filter((t) => /_MS$/.test(t))
        : [];
      const clearing = ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value) ? /^(|none)$/.test(value.text.trim()) : false;
      if (names.length > 0) for (const name of names) found.push({ file, line: lineOf(n), name, kind: "inline-css", value: consts.get(name) });
      else if (!clearing) unresolved.push(`${file}:${lineOf(n)} ${n.getText(sf).replace(/\s+/g, " ").slice(0, 100)}`);
    }
    // OrbitControls inertia.
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isPropertyAccessExpression(n.left) && n.left.name.text === "dampingFactor") {
      const r = strip(n.right);
      found.push({ file, line: lineOf(n), name: "dampingFactor", kind: "damping", value: ts.isNumericLiteral(r) ? Number(r.text) : undefined });
    }
    // The Web Animations API: not used today; if it appears, it must be resolvable like the rest.
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "animate" && n.arguments.length >= 2) {
      unresolved.push(`${file}:${lineOf(n)} ${n.getText(sf).replace(/\s+/g, " ").slice(0, 100)}`);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return { found, unresolved };
}

const scriptScan = files.filter((f) => /\.tsx?$/.test(f)).map((f) => scriptMotionIn(rel(f), readFileSync(f, "utf8")));
const scriptMotion: ScriptMotion[] = [
  ...scriptScan.flatMap((s) => s.found),
  // The eases the fabric steps (their divisor is `spec.durationMs`, so they are read from the owner).
  ...EASES.map((e) => ({ file: "src/fabric3d/emphasis.ts", line: 0, name: e.name, kind: "ease" as const, value: e.durationMs })),
];
/** One entry per constant: the same constant can drive several expressions. */
const scriptByName = new Map<string, ScriptMotion>();
for (const s of scriptMotion) if (!scriptByName.has(s.name)) scriptByName.set(s.name, s);

/* ── §4.8's table ─────────────────────────────────────────────────────────────────────────────── */

interface Row {
  raw: string;
  cells: string[];
  /** Backticked names in the first cell. */
  names: string[];
}
/** The body rows of a markdown table (header and separator dropped). */
function parseRows(text: string): Row[] {
  return text
    .split("\n")
    .filter((l) => l.startsWith("|") && !/^\|\s*-/.test(l) && !/^\|\s*Animation\s*\|/.test(l))
    .map((raw) => {
      const cells = raw.split("|").slice(1, -1).map((c) => c.trim());
      return { raw, cells, names: [...(cells[0] ?? "").matchAll(/`([^`]+)`/g)].map((m) => m[1]!) };
    });
}
const rows: Row[] = parseRows(s48);
const rowNaming = (name: string, table: readonly Row[] = rows): Row | undefined => table.find((r) => r.names.includes(name));
/** Every time stated in a cell, bold or not, in ms. */
const timesIn = (cell: string): number[] =>
  [...cell.replace(/\*\*/g, "").matchAll(/(\d+(?:\.\d+)?)\s*(ms|s)\b/g)].map((m) => Number(m[1]) * (m[2] === "s" ? 1000 : 1));
const boldTimesIn = (cell: string): number[] => [...cell.matchAll(/\*\*(\d+(?:\.\d+)?) ms\*\*/g)].map((m) => Number(m[1]));

/** One frame at 60 Hz, the display rate every settle figure in §4.8 is stated at. */
const FRAME_60 = 1000 / 60;
/** Acceptance C6: "under 300 ms except deliberate camera moves". */
const C6_BAR_MS = 300;
/** A row that takes an item out of the 300 ms bar must say so, in these words, with its reason. */
const EXEMPT = /Exempt from the 300 ms bar:/;

/** 60 fps settle time of an exported ease, as the lower half of this file measures it. */
function easeSettleMs(name: string): number | undefined {
  const spec = EASES.find((e) => e.name === name);
  if (spec === undefined) return undefined;
  const ch = createEaseChannel(0);
  for (let frames = 1; frames <= 10_000; frames += 1) {
    stepEaseChannel(ch, spec, 1, FRAME_60, false);
    if (ch.value === 1) return Math.round(frames * FRAME_60 * 1000) / 1000;
  }
  return undefined;
}

describe("the motion scan is live and its denominator is the real tree", () => {
  it("the CSS parser finds transitions, resolves tokens, and splits properties, delays and easings", () => {
    const planted = cssMotionIn(
      "planted.css",
      [
        "/* a comment { with braces; } */",
        ".a { color: red; transition: opacity var(--dur-medium) var(--ease-out), visibility 0s linear var(--dur-medium); }",
        "@media (max-width: 10px) { .b[data-x=\"a;b\"] .c { transition: transform 120ms ease-in-out; } }",
        ".d { animation: spin 900ms linear infinite; }",
        "@media (prefers-reduced-motion: reduce) { .a { transition-duration: 1ms !important; } }",
      ].join("\n"),
      new Map([
        ["--dur-medium", "240ms"],
        ["--ease-out", "cubic-bezier(0.16, 1, 0.3, 1)"],
      ]),
    );
    expect(planted.map((p) => [p.selector, p.kind, p.subjects, p.times, p.tokens, p.easings, p.literalTimes, p.infinite])).toEqual([
      [".a", "transition", ["opacity", "visibility"], [240, 0, 240], ["--dur-medium", "--dur-medium"], ["--ease-out", "linear"], [], false],
      ['.b[data-x="a;b"] .c', "transition", ["transform"], [120], [], ["ease-in-out"], [120], false],
      [".d", "animation", ["spin"], [900], [], ["linear"], [900], true],
      [".a", "transition", [], [1], [], [], [1], false],
    ]);
    expect(isReducedMotion(planted[3]!.atRules)).toBe(true);
    expect(planted[1]!.atRules).toEqual(["@media (max-width: 10px)"]);
  });

  it("the @keyframes scan is live: it finds planted names, including the deleted spinner's", () => {
    const planted = [
      "/* @keyframes commented-out { to { opacity: 0; } } */",
      ".stage-pending__spinner { animation: stage-pending-spin 900ms linear infinite; }",
      "@keyframes stage-pending-spin { to { transform: rotate(1turn); } }",
      "@keyframes\n  fade_in2 { from { opacity: 0; } }",
      "@-webkit-keyframes wk-pulse { 50% { opacity: .5; } }",
    ].join("\n");
    expect(keyframeNamesIn(planted)).toEqual(["stage-pending-spin", "fade_in2", "wk-pulse"]);
    expect(keyframeNamesIn(".a { color: red; }")).toEqual([]);
  });

  it("the script scan finds progress divisors, inline transitions and damping, and refuses what it cannot resolve", () => {
    const { found, unresolved } = scriptMotionIn(
      "planted.ts",
      [
        "const FADE_MS = 120;",
        "const LOOP_MS = 900;",
        "export function f(now: number, start: number, el: HTMLElement, c: { dampingFactor: number }) {",
        "  const t = Math.min(1, (now - start) / FADE_MS);",
        "  const loops = (now - start) / LOOP_MS;",
        "  el.style.transition = `opacity ${FADE_MS}ms linear`;",
        "  el.style.transition = '';",
        "  el.style.animation = 'spin 2s linear';",
        "  c.dampingFactor = 0.1;",
        "  el.animate([{ opacity: 0 }], 300);",
        "  return { style: { transition: 'color 90ms' }, t, loops };",
        "}",
      ].join("\n"),
    );
    expect(found.map((f) => [f.name, f.kind, f.value])).toEqual([
      ["FADE_MS", "progress", 120],
      ["LOOP_MS", "progress", 900],
      ["FADE_MS", "inline-css", 120],
      ["dampingFactor", "damping", 0.1],
    ]);
    expect(unresolved.map((u) => u.split(" ")[0])).toEqual(["planted.ts:8", "planted.ts:10", "planted.ts:11"]);
  });

  it("walks the real stylesheets and scripts, and finds the motion they carry", () => {
    expect(stylesheets.length, "the walk found the stylesheets").toBeGreaterThan(3);
    expect(stylesheets.map(rel)).toContain("src/core/tokens.css");
    expect(TOKENS.get("--dur-instant")).toBe("80ms");
    expect(cssMotion.length, "CSS transitions/animations in the tree").toBeGreaterThan(10);
    expect(cssCollapse.length, "reduced-motion collapse declarations in the tree").toBeGreaterThan(0);
    expect([...scriptByName.keys()].sort()).toEqual(expect.arrayContaining(["CAMERA_TWEEN_MS", "DRAW_ON_MS", "PACKET_LOOP_MS", "TIER_FADE_MS", "dampingFactor"]));
    expect(rows.length, "§4.8 table rows").toBeGreaterThan(5);
  });

  it("no script sets an inline transition or animation in a form the scan cannot resolve", () => {
    expect(scriptScan.flatMap((s) => s.unresolved), "inline motion the inventory cannot see").toEqual([]);
  });
});

/** Whether a CSS selector's classes are rendered: each one appears as a class token in some script or
 *  root HTML page. A transition on a class nothing applies never runs, and §4.8 must say so. */
const markup = [
  ...files.filter((f) => /\.(tsx?|html)$/.test(f)).map((f) => readFileSync(f, "utf8")),
  ...readdirSync(PKG)
    .filter((n) => n.endsWith(".html"))
    .map((n) => readFileSync(resolve(PKG, n), "utf8")),
].join("\n");
function rendered(selector: string): boolean {
  const classes = [...selector.matchAll(/\.([\w-]+)/g)].map((m) => m[1]!);
  return classes.every((c) => new RegExp(`(^|[\\s"'\`{])${c.replace(/-/g, "\\-")}(?=[\\s"'\`}]|$)`, "m").test(markup));
}
const NEVER_RENDERED = /NEVER RENDERED/;

/** Forward: each CSS motion declaration against the row that names it. */
function cssProblems(table: readonly Row[]): string[] {
  const problems: string[] = [];
  for (const m of cssMotion) {
    const where = `${m.file}:${m.line} \`${m.selector}\``;
    const row = rowNaming(m.selector, table);
    if (row === undefined) {
      problems.push(`${where}: no §4.8 row names this selector (${m.kind} ${m.subjects.join(", ")} ${m.times.join("/")} ms)`);
      continue;
    }
    const duration = row.cells[1] ?? "";
    const easing = row.cells[2] ?? "";
    for (const t of new Set(m.times.filter((x) => x > 0))) {
      if (!boldTimesIn(duration).includes(t)) problems.push(`${where}: the row's Duration cell does not state **${t} ms**`);
    }
    for (const sub of m.subjects) if (!new RegExp(`\\b${sub}\\b`).test(duration)) problems.push(`${where}: the row does not name the transitioned ${sub}`);
    for (const tok of new Set(m.tokens)) if (!duration.includes(`\`${tok}\``)) problems.push(`${where}: the row does not name the token \`${tok}\``);
    for (const e of new Set(m.easings)) if (!easing.includes(e)) problems.push(`${where}: the Easing cell does not name ${e}`);
    if (!/reduced motion/i.test(row.raw)) problems.push(`${where}: the row does not state its reduced-motion behaviour`);
    const isRendered = rendered(m.selector);
    if (!isRendered && !NEVER_RENDERED.test(row.raw)) problems.push(`${where}: no markup applies this selector, and the row does not say NEVER RENDERED`);
    if (isRendered && NEVER_RENDERED.test(row.raw)) problems.push(`${where}: the row says NEVER RENDERED, but markup applies the selector`);
  }
  return problems;
}

/** Forward: each script-driven item against the row that names it. */
function scriptProblems(table: readonly Row[]): string[] {
  const problems: string[] = [];
  for (const sm of scriptByName.values()) {
    const where = `${sm.file}:${sm.line} \`${sm.name}\``;
    if (sm.value === undefined) {
      problems.push(`${where}: no literal value to inventory`);
      continue;
    }
    const row = rowNaming(sm.name, table);
    if (row === undefined) {
      problems.push(`${where}: no §4.8 row names it`);
      continue;
    }
    const duration = row.cells[1] ?? "";
    if (sm.kind === "damping") {
      if (!duration.includes(`**${sm.value}**`)) problems.push(`${where}: the row does not state the factor **${sm.value}**`);
    } else if (boldTimesIn(duration)[0] !== sm.value) {
      problems.push(`${where}: the row's first bold duration is ${boldTimesIn(duration)[0]} ms, the code's is ${sm.value} ms`);
    }
    if (!/reduced motion/i.test(row.raw)) problems.push(`${where}: the row does not state its reduced-motion behaviour`);
  }
  return problems;
}

/** Reverse: every row names something the code has, and states only times the code has for it. */
function reverseProblems(table: readonly Row[]): string[] {
  const cssBySelector = new Map<string, CssMotion[]>();
  for (const m of cssMotion) cssBySelector.set(m.selector, [...(cssBySelector.get(m.selector) ?? []), m]);
  const source = files.map((f) => readFileSync(f, "utf8")).join("\n");
  const problems: string[] = [];
  for (const row of table) {
    const label = row.cells[0] ?? row.raw;
    const items = row.names.filter((n) => cssBySelector.has(n) || scriptByName.has(n));
    if (items.length === 0) problems.push(`"${label}": names no animation the code declares`);
    for (const n of row.names) {
      const exists = cssBySelector.has(n) || scriptByName.has(n) || source.includes(n) || statSafe(resolve(PKG, n));
      if (!exists) problems.push(`"${label}": \`${n}\` exists nowhere in src/`);
    }
    /* The times the code has for what this row names: exact for a duration or delay; for an ease's
       60 fps settle time, the measured value up to 1 ms of rounding above it. */
    const exact = new Set<number>();
    const settles: number[] = [];
    for (const n of items) {
      for (const m of cssBySelector.get(n) ?? []) for (const t of m.times) exact.add(t);
      const sm = scriptByName.get(n);
      if (sm !== undefined && sm.value !== undefined && sm.kind !== "damping") exact.add(sm.value);
      const settle = easeSettleMs(n);
      if (settle !== undefined) settles.push(settle);
    }
    for (const t of timesIn(row.cells[1] ?? "")) {
      if (!exact.has(t) && !settles.some((s) => t >= s && t < s + 1)) {
        problems.push(`"${label}": states ${t} ms, which is no time the code gives ${items.join(", ") || "anything it names"} (has: ${[...exact, ...settles].join(", ") || "none"})`);
      }
    }
  }
  return problems;
}

describe("§4.8 names every animation the code declares, with the code's own times", () => {
  it("every CSS transition/animation is on a row with its resolved times, properties, tokens, easings and rendered-ness", () => {
    const problems = cssProblems(rows);
    expect(problems, `§4.8 against the stylesheets:\n${problems.join("\n")}`).toEqual([]);
    expect(cssMotion.length).toBeGreaterThan(0);
  });

  it("every script-driven animation is on a row whose first bold duration is the constant's value", () => {
    const problems = scriptProblems(rows);
    expect(problems, `§4.8 against the scripts:\n${problems.join("\n")}`).toEqual([]);
    expect(scriptByName.size).toBeGreaterThan(0);
  });

  it("every §4.8 row names something the code has, and states no time the code does not have", () => {
    const problems = reverseProblems(rows);
    expect(problems, `§4.8 rows that are not true of the code:\n${problems.join("\n")}`).toEqual([]);
  });

  it("is live: the rows the refuter disproved, and a table missing the transitions, are all rejected", () => {
    /* Verbatim from design-brief.md at d3e2a1c. The same checks, over that text, must name the stagger
       that never existed, the palette animation that never existed, and every omitted transition. */
    const old = parseRows(
      [
        "| Trace path draw-on | **240 ms total**, staggered 18 ms per hop | `--ease-out` | The stagger *is* the information — it shows hop order. Total capped at 240 ms regardless of hop count. |",
        "| Command palette | **140 ms** | `--ease-out` | |",
        "| Panel / inspector open | **240 ms** height, **140 ms** opacity | `--ease-out` | |",
      ].join("\n"),
    );
    expect(reverseProblems(old)).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/^"Trace path draw-on": names no animation/),
        expect.stringMatching(/^"Trace path draw-on": states 18 ms/),
        expect.stringMatching(/^"Command palette": states 140 ms/),
        expect.stringMatching(/^"Panel \/ inspector open": names no animation/),
      ]),
    );
    // A draw-on row that names the constant but keeps the stagger still fails, on the 18 ms.
    const named = parseRows("| Trace path draw-on (`DRAW_ON_MS`) | **240 ms** total, staggered 18 ms per hop | x | Under reduced motion: instant. |");
    expect(reverseProblems(named)).toEqual([expect.stringMatching(/states 18 ms, which is no time the code gives DRAW_ON_MS/)]);
    // With none of the CSS rows, every stylesheet transition is reported by selector.
    const missing = cssProblems(old);
    expect(missing.length).toBe(cssMotion.length);
    expect(missing.join("\n")).toContain("`.skip-link`: no §4.8 row names this selector");
    // A rendered selector falsely marked NEVER RENDERED is caught; the detector tells the two apart.
    const skip = cssMotion.find((m) => m.selector === ".skip-link");
    expect(skip, "the skip link's transition is in the scan").toBeDefined();
    const liar = parseRows("| x (`.skip-link`) | **140 ms** (`--dur-fast`) top | `--ease-out` | NEVER RENDERED. Under reduced motion: 1 ms. |");
    expect(cssProblems(liar)).toContain(`${skip!.file}:${skip!.line} \`.skip-link\`: the row says NEVER RENDERED, but markup applies the selector`);
    expect(rendered(".skip-link")).toBe(true);
    expect(rendered(".definitely-not-a-class-in-this-tree")).toBe(false);
  });
});

function statSafe(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

describe("C6: motion ends under 300 ms at 60 Hz unless §4.8 exempts it by name", () => {
  it("every CSS transition's end state is on screen before 300 ms, and it collapses under reduced motion", () => {
    const problems: string[] = [];
    for (const m of cssMotion) {
      const worst = Math.max(0, ...m.ends);
      if (worst + FRAME_60 >= C6_BAR_MS && !EXEMPT.test(rowNaming(m.selector)?.raw ?? "")) {
        problems.push(`${m.file}:${m.line} \`${m.selector}\` ends at ${worst} ms (+1 frame)`);
      }
      if (m.literalTimes.length > 0) problems.push(`${m.file}:${m.line} \`${m.selector}\` uses literal time(s) ${m.literalTimes.join(", ")} ms, which the reduced-motion tokens cannot collapse`);
      if (m.infinite) problems.push(`${m.file}:${m.line} \`${m.selector}\` loops forever`);
    }
    expect(problems).toEqual([]);
    expect(cssMotion.length).toBeGreaterThan(0);
  });

  it("every reduced-motion override collapses motion rather than adding it (<= 1 ms)", () => {
    const over = cssCollapse.filter((m) => m.times.some((t) => t > 1)).map((m) => `${m.file}:${m.line} ${m.selector} ${m.times.join("/")}`);
    expect(over).toEqual([]);
    expect(cssCollapse.length).toBeGreaterThan(0);
  });

  it("every script-driven duration ends before 300 ms at 60 Hz, unless its row is exempt", () => {
    const problems: string[] = [];
    let judged = 0;
    for (const s of scriptByName.values()) {
      if (s.kind === "damping" || s.value === undefined) continue;
      judged += 1;
      if (s.value + FRAME_60 >= C6_BAR_MS && !EXEMPT.test(rowNaming(s.name)?.raw ?? "")) {
        problems.push(`${s.file}:${s.line} ${s.name} = ${s.value} ms can first show its end state at ${(s.value + FRAME_60).toFixed(1)} ms`);
      }
    }
    expect(problems).toEqual([]);
    expect(judged).toBeGreaterThan(3);
  });

  it("the exemptions are exactly the deliberate camera moves and the bounded packet loop", () => {
    /* Read back from the brief so the set of exemptions is visible here, not only in prose: C6 allows
       "deliberate camera moves"; the packet marker is the one loop, bounded by PACKET_LOOPS. */
    const exempt = rows.filter((r) => EXEMPT.test(r.raw)).flatMap((r) => r.names.filter((n) => scriptByName.has(n) || cssMotion.some((m) => m.selector === n)));
    expect(exempt.sort()).toEqual(["CAMERA_TWEEN_MS", "PACKET_LOOP_MS", "dampingFactor"]);
  });
});

describe("the one looping animation", () => {
  it("every 'only looping animation' claim is about the one loop that runs, the packet marker", () => {
    /* App.css and flow.ts each claimed to be "the only looping animation" — a contradiction. The
       truth, read from the code: the one loop the product declares is the packet marker, bounded at
       PACKET_LOOPS (the unbounded `stage-pending-spin` App.css also declared was never rendered and
       is deleted, O18). So a superlative is true only when it is about the packet marker.
       Discovered from the text, not from a list of files: any comment or brief row making the claim
       is checked, wherever it is. */
    const norm = (t: string) => t.replace(/\s*\*\s*/g, " ").replace(/\s+/g, " ");
    const sources = [
      ...files.filter((f) => /\.(css|tsx?)$/.test(f)).map((f) => ({ where: rel(f), text: norm(readFileSync(f, "utf8")) })),
      { where: "docs/design-brief.md §4.8", text: norm(s48) },
    ];
    const bad: string[] = [];
    let claims = 0;
    for (const { where, text } of sources) {
      for (const m of text.matchAll(/\bonly\s+looping\s+animation\b/gi)) {
        claims++;
        const tail = text.slice(m.index!);
        const end = tail.search(/[.;]\s/);
        const around = text.slice(Math.max(0, m.index! - 120), m.index! + (end < 0 ? tail.length : end));
        if (!/packet/i.test(around)) bad.push(`${where}: …${text.slice(Math.max(0, m.index! - 80), m.index! + 60)}…`);
      }
    }
    expect(bad, "a claim to be the only loop, about something other than the packet marker").toEqual([]);
    expect(claims, "the scan found the claims it is meant to police").toBeGreaterThan(0);
  });

  it("no stylesheet declares an unbounded loop and nothing renders the deleted spinner", () => {
    expect(cssMotion.filter((m) => m.infinite).map((m) => `${m.file}: ${m.selector}`)).toEqual([]);
    // Every @keyframes a stylesheet declares is played by some inventoried animation (none today).
    const keyframes = [
      ...stylesheets.flatMap((f) => keyframeNamesIn(readFileSync(f, "utf8"))),
      ...htmlStyles.flatMap((h) => keyframeNamesIn(h.css)),
    ];
    const played = new Set(cssMotion.filter((m) => m.kind === "animation").flatMap((m) => m.subjects));
    expect(keyframes.filter((k) => !played.has(k)), "@keyframes no inventoried animation plays").toEqual([]);
    const users = files
      .filter((f) => /\.(tsx?|html)$/.test(f))
      .filter((f) => readFileSync(f, "utf8").includes("stage-pending__spinner"))
      .map(rel);
    expect(users).toEqual([]);
    expect(s48, "§4.8 still lists the deleted spinner").not.toMatch(/stage-pending-spin|stage-pending__spinner/);
  });
});

/* ── rAF-driven eases (C6, independent refuter 2026-09-22) ─────────────────────────────────────
 *
 * WHY. Everything above sees only what CSS animates. The fades a reader actually notices on the
 * fabric — dim/undim, the hover rim, the selection halo — are stepped by JavaScript on every
 * animation frame, and they were EXPONENTIAL: `k = min(1, dt / RECEDE_MS); cur += (tgt - cur) * k`,
 * snapping only inside an epsilon. `RECEDE_MS = 240` was therefore a time CONSTANT, not a duration:
 * measured, the recession settled at 1,350 ms, the hover at ~417 ms and the halo at ~917 ms, while
 * §4.8 promised 240 / 80 / 140 ms. The inventory stayed green because it could not see any of them.
 *
 * So this half is structural too. It parses every source file with the TypeScript compiler and
 * finds every per-frame interpolation of the two shapes an exponential ease takes —
 *   (a) an accumulator stepped towards a target: `x += (t - x) * k`, `x = x + (t - x) * k`;
 *   (b) a rate from a frame delta over a `*_MS` constant: `k = f(dt / SOMETHING_MS)`, and any
 *       `a + (b - a) * k` whose factor is such a rate;
 *   (c) the same ease behind a library name: any `damp(...)` call (three's `MathUtils.damp` IS an
 *       exponential ease), a self-assigned `x = lerp(x, t, k)`, and its in-place method spelling
 *       `v.lerp(t, k)` / `q.slerp(t, k)` on a receiver not given an explicit start in the same
 *       function —
 * and fails on any of them outside the ease owner (`src/fabric3d/emphasis.ts`). Then it steps every
 * ease the owner exports at 60 fps and holds its measured settle time against the row §4.8 states
 * for it, read from the brief itself.
 */

const EASE_OWNER = "src/fabric3d/emphasis.ts";

/** Every exponential-ease shape in one source text, as `line: text` strings. */
function findExponentialSteps(fileName: string, text: string): string[] {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const hits: string[] = [];
  const strip = (e: ts.Expression): ts.Expression => {
    let x = e;
    while (ts.isParenthesizedExpression(x) || ts.isAsExpression(x) || ts.isNonNullExpression(x)) x = x.expression;
    return x;
  };
  const same = (a: ts.Node, b: ts.Node): boolean => a.getText(sf).replace(/\s+/g, "") === b.getText(sf).replace(/\s+/g, "");
  /** Whether identifier `id` is a parameter of a function enclosing it — the per-frame delta a
   *  step function is handed (`step(dt)`), as opposed to a local elapsed time (`now - start`). */
  const isEnclosingParam = (id: ts.Identifier): boolean => {
    for (let p: ts.Node | undefined = id.parent; p !== undefined; p = p.parent) {
      if (ts.isFunctionLike(p) && p.parameters.some((q) => ts.isIdentifier(q.name) && q.name.text === id.text)) return true;
    }
    return false;
  };
  /** `dt / FOO_MS` inside `e` (not inside a nested function): a frame delta over a millisecond
   *  constant, i.e. a per-frame RATE — the signature of an exponential ease. */
  const hasRate = (e: ts.Node): boolean => {
    let found = false;
    const visit = (n: ts.Node): void => {
      if (found || (n !== e && ts.isFunctionLike(n))) return;
      if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.SlashToken) {
        const l = strip(n.left);
        const r = strip(n.right);
        if (ts.isIdentifier(l) && ts.isIdentifier(r) && /_MS$/.test(r.text) && isEnclosingParam(l)) found = true;
      }
      ts.forEachChild(n, visit);
    };
    visit(e);
    return found;
  };
  /** `(t - x) * k` or `k * (t - x)`: returns [x, k] when it is one. */
  const towards = (e: ts.Expression): [ts.Expression, ts.Expression] | null => {
    const m = strip(e);
    if (!ts.isBinaryExpression(m) || m.operatorToken.kind !== ts.SyntaxKind.AsteriskToken) return null;
    for (const [d, k] of [[m.left, m.right], [m.right, m.left]] as const) {
      const diff = strip(d);
      if (ts.isBinaryExpression(diff) && diff.operatorToken.kind === ts.SyntaxKind.MinusToken) return [diff.right, k];
    }
    return null;
  };
  /** Whether `recv` is given a fresh value earlier in the function enclosing `at` — `recv = …`, or
   *  a three setter on it (`recv.copy(…)`, `recv.set…(…)`, `recv.fromArray(…)`) — so an in-place
   *  lerp of it that follows starts from an explicit value rather than from last frame's. */
  const reinitialisedBefore = (recv: ts.Expression, at: ts.Node): boolean => {
    let fn: ts.Node | undefined = at.parent;
    while (fn !== undefined && !ts.isFunctionLike(fn)) fn = fn.parent;
    if (fn === undefined) return false;
    let found = false;
    const scan = (m: ts.Node): void => {
      if (found || m.getStart(sf) >= at.getStart(sf)) return;
      if (ts.isBinaryExpression(m) && m.operatorToken.kind === ts.SyntaxKind.EqualsToken && same(m.left, recv)) found = true;
      if (
        ts.isCallExpression(m) &&
        ts.isPropertyAccessExpression(m.expression) &&
        /^(copy|set\w*|fromArray)$/.test(m.expression.name.text) &&
        same(m.expression.expression, recv)
      ) {
        found = true;
      }
      ts.forEachChild(m, scan);
    };
    ts.forEachChild(fn, scan);
    return found;
  };
  const rates = new Set<string>();
  const where = (n: ts.Node): string => `${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}: ${n.getText(sf).replace(/\s+/g, " ").slice(0, 90)}`;
  const visit = (n: ts.Node): void => {
    /* (c) `damp(x, t, lambda, dt)` / `MathUtils.damp(...)`: three's frame-rate-independent
       exponential ease, i.e. shape (a) behind a function name. Any call to it is one. */
    if (ts.isCallExpression(n) && /(^|\.)damp$/i.test(n.expression.getText(sf))) hits.push(where(n));
    /* (c) the METHOD spelling of a self-assigned lerp: `v.lerp(t, k)` / `q.slerp(t, k)` mutate `v`,
       so on a value that persists across frames they are `v = v + (t - v) * k`. A lerp from an
       explicit start is not: a receiver that is itself a call (`v.copy(from).lerp(to, p)`), or one
       re-initialised earlier in the same function (`out.copy(a); …; out.lerp(b, t)`), or the
       two-endpoint forms (`lerpVectors`, `lerpColors`), which the name pattern excludes. */
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && /^s?lerp$/.test(n.expression.name.text)) {
      const recv = strip(n.expression.expression);
      if (!ts.isCallExpression(recv) && !reinitialisedBefore(recv, n)) hits.push(where(n));
    }
    // (b) a rate: `const k = Math.min(1, dt / RECEDE_MS)` (declaration or assignment)
    if (ts.isVariableDeclaration(n) && n.initializer !== undefined && hasRate(n.initializer)) {
      hits.push(where(n));
      if (ts.isIdentifier(n.name)) rates.add(n.name.text);
    }
    if (ts.isBinaryExpression(n)) {
      const op = n.operatorToken.kind;
      if (op === ts.SyntaxKind.EqualsToken && hasRate(n.right)) {
        hits.push(where(n));
        if (ts.isIdentifier(n.left)) rates.add(n.left.text);
      }
      // (a) `x += (t - x) * k`
      if (op === ts.SyntaxKind.PlusEqualsToken) {
        const t = towards(n.right);
        if (t !== null && same(t[0], n.left)) hits.push(where(n));
      }
      // (c) the library spelling of (a): `x = lerp(x, t, k)` / `x = MathUtils.lerp(x, t, k)`
      if (op === ts.SyntaxKind.EqualsToken) {
        const call = strip(n.right);
        if (ts.isCallExpression(call) && /(^|\.)lerp$/i.test(call.expression.getText(sf)) && call.arguments[0] !== undefined && same(call.arguments[0], n.left)) {
          hits.push(where(n));
        }
      }
      // (a) `x = x + (t - x) * k`, and (b) `a + (b - a) * k` with a rate factor
      if (op === ts.SyntaxKind.PlusToken) {
        const t = towards(n.right);
        if (t !== null && same(t[0], n.left)) {
          const parent = n.parent;
          const selfAssign =
            ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.EqualsToken && parent.right === n && same(parent.left, n.left);
          const k = strip(t[1]);
          const rateFactor = hasRate(k) || (ts.isIdentifier(k) && rates.has(k.text));
          if (selfAssign || rateFactor) hits.push(where(n));
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return [...new Set(hits)];
}

describe("§4.8 sees rAF-driven eases: no exponential step outside the ease owner", () => {
  it("the scanner is live: it flags an exponential step planted in a synthetic source", () => {
    const planted = [
      "const HOVER_MS = 80;",
      "export function step(dt: number) {",
      "  const kh = Math.min(1, dt / HOVER_MS);",
      "  hoverAlpha += (hoverTarget - hoverAlpha) * kh;",
      "  cur = cur + (tgt - cur) * 0.2;",
      "  const next = cur + (tgt - cur) * kh;",
      "  halo = MathUtils.damp(halo, target, 12, dt);",
      "  rim = lerp(rim, target, 0.2);",
      "  rig.position.lerp(goal, 0.1);",
      "  orient.slerp(qGoal, kh);",
      "}",
    ].join("\n");
    const hits = findExponentialSteps("planted.ts", planted);
    expect(hits.some((h) => h.startsWith("3:")), `rate not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("4:")), `+= step not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("5:")), `x = x + (t-x)*k not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("6:")), `lerp by a rate not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("7:")), `damp() not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("8:")), `x = lerp(x, t, k) not flagged: ${hits.join(" | ")}`).toBe(true);
    /* The METHOD spelling of a self-assigned lerp: three's Vector3/Color/Quaternion `lerp`/`slerp`
       mutate their receiver, so `v.lerp(t, k)` on a value that persists across calls IS
       `v = v + (t - v) * k` (review 2c: recorded as the scanner's blind spot, now closed). */
    expect(hits.some((h) => h.startsWith("9:")), `in-place v.lerp(t, k) not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("10:")), `in-place q.slerp(t, k) not flagged: ${hits.join(" | ")}`).toBe(true);
    // ...and a finite-duration ease or a geometric lerp is not an exponential step: a lerp from an
    // explicit start (a `copy` chain, or a receiver re-initialised earlier in the same function).
    const finite = [
      "export function f(nowMs: number, start: number, a: number, b: number, t: number) {",
      "  const p = Math.min(1, (nowMs - start) / CAMERA_TWEEN_MS);",
      "  v.copy(from).lerp(to, p);",
      "  return a + (b - a) * t + p;",
      "}",
      "export function tint(out: Color, y: number) {",
      "  out.copy(base);",
      "  out.setHSL(0, 0, 0.5);",
      "  out.lerp(white, 1 - y);",
      "  mid.lerpVectors(a, b, 0.5);",
      "  return out;",
      "}",
    ].join("\n");
    expect(findExponentialSteps("finite.ts", finite)).toEqual([]);
  });

  it("finds none anywhere in src/ except the ease owner", () => {
    const offenders = files
      .filter((f) => /\.tsx?$/.test(f) && rel(f) !== EASE_OWNER)
      .flatMap((f) => findExponentialSteps(f, readFileSync(f, "utf8")).map((h) => `${rel(f)}:${h}`));
    expect(offenders, "a per-frame exponential ease outside src/fabric3d/emphasis.ts").toEqual([]);
  });

  it("the ease owner itself steps no exponential ease either: every ease there is finite", () => {
    const own = findExponentialSteps(EASE_OWNER, readFileSync(resolve(PKG, EASE_OWNER), "utf8"));
    expect(own, "the owner still carries an exponential step").toEqual([]);
  });
});

describe("§4.8 states, for every ease the owner exports, the settle time the ease actually has", () => {
  /** 60 fps, the display rate §4.8's settle figures are stated at. */
  const DT = 1000 / 60;
  /** Step one ease 0 -> 1 at 60 fps; the time of the first frame whose value IS the target. */
  const settleMs = (spec: (typeof EASES)[number], reduced = false): number => {
    const ch = createEaseChannel(0);
    for (let frames = 1; frames <= 10_000; frames += 1) {
      stepEaseChannel(ch, spec, 1, DT, reduced);
      if (ch.value === 1) return frames * DT;
    }
    return Infinity;
  };
  const rowOf = (name: string): string | undefined =>
    s48.split("\n").find((l) => l.startsWith("|") && l.includes("`" + name + "`"));

  it("the owner exports the eases the fabric steps (the check is not vacuous)", () => {
    expect(EASES.map((e) => e.name).sort()).toEqual(["HOVER_MS", "RECEDE_MS", "SELECT_MS"]);
  });

  for (const spec of EASES) {
    it(`${spec.name}: the §4.8 row's duration is the ease's, and its stated settle time is the measured one`, () => {
      const row = rowOf(spec.name);
      expect(row, `§4.8 has no row naming \`${spec.name}\``).toBeDefined();
      const duration = /\*\*(\d+(?:\.\d+)?) ms\*\*/.exec(row!)?.[1];
      expect(Number(duration), `${spec.name}: the row's bold duration`).toBe(spec.durationMs);
      const stated = /settles in \*\*(\d+(?:\.\d+)?) ms\*\* at 60 fps/.exec(row!)?.[1];
      expect(stated, `${spec.name}: the row states "settles in **N ms** at 60 fps"`).toBeDefined();
      // Rounded to the microsecond: 15 frames of 1000/60 ms is 250.00000000000003 in doubles.
      const measured = Math.round(settleMs(spec) * 1000) / 1000;
      // No later than stated, and stated no more than a millisecond of rounding above it.
      expect(measured, `${spec.name} settles at ${measured.toFixed(2)} ms, later than §4.8 states`).toBeLessThanOrEqual(Number(stated));
      expect(Number(stated) - measured, `${spec.name}: §4.8 overstates the settle time`).toBeLessThan(1);
      // And the C6 bar itself: under 300 ms.
      expect(measured).toBeLessThan(300);
      expect(row!, `${spec.name}: reduced-motion behaviour`).toMatch(/reduced motion/i);
    });

    it(`${spec.name}: under reduced motion the ease lands on its target in the frame it starts`, () => {
      expect(settleMs(spec, true)).toBe(DT);
    });
  }
});
