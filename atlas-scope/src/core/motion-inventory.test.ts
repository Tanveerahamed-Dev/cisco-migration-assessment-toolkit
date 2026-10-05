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
 * and asserted nothing (the runtime assertion guard, src/test-support/test-setup.ts, now fails that shape).
 *
 * WHAT IS DISCOVERED, from the code, not from a list:
 *   CSS  every `transition`, `transition-duration`, `animation` and `animation-duration` declaration in
 *        every stylesheet under src/ (and every `<style>` in a root HTML page), with each duration and
 *        delay RESOLVED through the `--dur-*` tokens in src/core/tokens.css, keyed by its selector.
 *        Declarations inside `@media (prefers-reduced-motion: reduce)` are the collapse, not motion:
 *        they are held to <= 1 ms instead.
 *   JS   every `*_MS` constant that is the DIVISOR of a progress fraction (`(now - start) / X_MS`,
 *        `elapsed / X_MS`), is interpolated into an inline `transition`/`animation`, or is the
 *        `durationMs` of an ease spec (a fade the render loop steps, like the tier cross-fade since
 *        C5 2026-09-26); every ease the ease owner exports; every OrbitControls `dampingFactor`. And any inline `transition` or
 *        `animation` a script sets in a form this scan cannot resolve fails, so a new spelling
 *        cannot hide. And every HOLD before such motion: a `setTimeout` whose callback starts it
 *        (directly or through the local functions it calls — and a script-STEPPED fade starts where
 *        a function uses what the ease owner exports to run one: see `easeOwnerStarters`), with its delay resolved through a local
 *        constant or an object constant's numeric property anywhere in src/ (C6, 2026-09-23: the
 *        tier step-down hold had no §4.8 bound). A delay it cannot resolve fails the same way.
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
import * as easeOwner from "../fabric3d/emphasis";
import { EASES, createEaseChannel, stepEaseChannel, type EaseSpec } from "../fabric3d/emphasis";

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
  /** `delay`: the wait before a timer starts script-set motion (a hold), not the motion itself. */
  kind: "progress" | "inline-css" | "ease" | "damping" | "delay";
  /** The constant's value: ms for a duration or a delay, a per-frame factor for damping. */
  value: number | undefined;
}

const stripExpr = (e: ts.Expression): ts.Expression => {
  let x = e;
  while (ts.isParenthesizedExpression(x) || ts.isAsExpression(x) || ts.isNonNullExpression(x) || ts.isSatisfiesExpression(x)) x = x.expression;
  return x;
};

/** `NAME.prop` -> value for every numeric property of an object-literal constant one script declares
 *  (`const X = { … }`, `const X: T = { … }`, `Object.freeze({ … })`): how a delay spelled as an
 *  options object's property (`TIER_FADE_HOLD_DEFAULTS.maxHoldMs`) is resolved from its owner. */
export function numericPropsIn(text: string): Map<string, number> {
  const sf = ts.createSourceFile("props.ts", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const out = new Map<string, number>();
  const visit = (n: ts.Node): void => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined) {
      let init = stripExpr(n.initializer);
      if (ts.isCallExpression(init) && init.expression.getText(sf) === "Object.freeze" && init.arguments[0] !== undefined) init = stripExpr(init.arguments[0]);
      if (ts.isObjectLiteralExpression(init)) {
        for (const p of init.properties) {
          if (ts.isPropertyAssignment(p) && ts.isIdentifier(p.name) && ts.isNumericLiteral(stripExpr(p.initializer))) {
            out.set(`${n.name.text}.${p.name.text}`, Number((stripExpr(p.initializer) as ts.NumericLiteral).text));
          }
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

/** The ease owner: the one module allowed to step a JavaScript ease (see the lower half of this file). */
const EASE_OWNER = "src/fabric3d/emphasis.ts";

/**
 * EVERY ease the owner exports, derived from its exports rather than from the hand-kept `EASES` list
 * (C5 verification, 2026-09-26: the tier cross-fade's `TIER_FADE_EASE` is stepped by the render loop
 * but is not in `EASES`, so a settle check over `EASES` covered a named subset of the class). An
 * ease is any exported value shaped like an EaseSpec. The denominator test below cross-checks this
 * against the owner's SOURCE (every `export const X: EaseSpec`), so neither derivation can drift.
 */
const isEaseSpec = (v: unknown): v is EaseSpec =>
  typeof v === "object" &&
  v !== null &&
  typeof (v as EaseSpec).name === "string" &&
  typeof (v as EaseSpec).durationMs === "number" &&
  typeof (v as EaseSpec).curve === "string";
const OWNER_EASE_EXPORTS: readonly (readonly [string, EaseSpec])[] = Object.entries(easeOwner).filter((e): e is [string, EaseSpec] => isEaseSpec(e[1]));
const OWNER_EASES: readonly EaseSpec[] = OWNER_EASE_EXPORTS.map(([, v]) => v);

/**
 * What the ease owner exports that RUNS a script-stepped fade, found from the owner's source, not
 * from a list (C5, 2026-09-26). The tier cross-fade stopped being an inline CSS transition: its hold's
 * backstop timer now starts a fade the render loop steps (`createTierFade`), so a scan that only knew
 * `el.style.transition = …` as "starting motion" lost the hold AND the fade at once — measured, the
 * "is live" and hold cases went red on exactly that. The class is "a function that sets a fade
 * going", and the owner is where every such fade is defined, so:
 *   - an owner DURATION is a `const X_MS = <number>`;
 *   - an owner SPEC is a `const` whose initializer names a duration or another spec (`RECEDE_EASE`,
 *     `TIER_FADE_EASE`, `EASES`);
 *   - an owner function RUNS a fade when its body names a duration, a spec, or another such function.
 * Exported names in any of the three are returned; a script that references one (imported from the
 * owner, under any local alias) is doing so to run an ease on the fabric.
 */
export function easeOwnerStarters(text: string): Set<string> {
  const sf = ts.createSourceFile(EASE_OWNER, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const exported = (n: ts.Node): boolean =>
    (ts.canHaveModifiers(n) ? ts.getModifiers(n) ?? [] : []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
  const reach = new Set<string>();
  const decls: { name: string; body: ts.Node; isExported: boolean }[] = [];
  for (const st of sf.statements) {
    if (ts.isVariableStatement(st)) {
      for (const d of st.declarationList.declarations) {
        if (!ts.isIdentifier(d.name) || d.initializer === undefined) continue;
        if (/_MS$/.test(d.name.text) && ts.isNumericLiteral(stripExpr(d.initializer))) reach.add(d.name.text);
        decls.push({ name: d.name.text, body: d.initializer, isExported: exported(st) });
      }
    } else if (ts.isFunctionDeclaration(st) && st.name !== undefined && st.body !== undefined) {
      decls.push({ name: st.name.text, body: st.body, isExported: exported(st) });
    } else if (ts.isClassDeclaration(st) && st.name !== undefined) {
      /* A class is a declaration whose methods start motion like a function's body (P3C-V2-2: the tier-fade slot
         is a class, so its methods run only on the instance). Left out, a starter built on one reached nothing. */
      decls.push({ name: st.name.text, body: st, isExported: exported(st) });
    }
  }
  const names = (root: ts.Node): boolean => {
    let hit = false;
    const scan = (n: ts.Node): void => {
      if (hit) return;
      if (ts.isIdentifier(n) && reach.has(n.text)) hit = true;
      else ts.forEachChild(n, scan);
    };
    scan(root);
    return hit;
  };
  for (let grew = true; grew; ) {
    grew = false;
    for (const d of decls) if (!reach.has(d.name) && names(d.body)) (reach.add(d.name), (grew = true));
  }
  const exportedNames = new Set(decls.filter((d) => d.isExported).map((d) => d.name));
  return new Set([...reach].filter((n) => exportedNames.has(n)));
}

/** Every animation-timing constant one script declares, found by what the code DOES with it.
 *  `external` resolves `NAME.prop` delays declared in another file (see `numericPropsIn`);
 *  `ownerStarters` is `easeOwnerStarters` of the ease owner, so a delayed start of a script-stepped
 *  fade is found as surely as one of an inline CSS transition. */
export function scriptMotionIn(
  file: string,
  text: string,
  external: ReadonlyMap<string, number> = new Map(),
  ownerStarters: ReadonlySet<string> = new Set(),
): { found: ScriptMotion[]; unresolved: string[] } {
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  /* Local names this file binds to an owner starter: `import { createTierFade as begin } from "./emphasis"`.
     Resolved by PATH, so another module's same-named export is not mistaken for the owner's. */
  const ownerLocal = new Set<string>();
  const ownerPath = EASE_OWNER.replace(/\.ts$/, "");
  for (const st of sf.statements) {
    if (!ts.isImportDeclaration(st) || !ts.isStringLiteral(st.moduleSpecifier)) continue;
    const spec = st.moduleSpecifier.text;
    if (!spec.startsWith(".")) continue;
    const target = relative(PKG, resolve(PKG, dirname(file), spec)).split("\\").join("/").replace(/\.ts$/, "");
    if (target !== ownerPath) continue;
    const bindings = st.importClause?.namedBindings;
    if (bindings !== undefined && ts.isNamedImports(bindings)) {
      for (const el of bindings.elements) if (ownerStarters.has((el.propertyName ?? el.name).text)) ownerLocal.add(el.name.text);
    }
  }
  /* ...and every local VALUE obtained from one, to a fixed point (R4-VR1-4, 2026-09-27): the tier fade
     is now run through an object the owner builds (`const tierFade = createTierFadeSlot(…)`, then
     `const handle = tierFade.presented(…)`, then `handle.start()` in a timer's callback). Matched by
     name only, the timer that starts it was lost; a value derived from an owner starter carries it. */
  const derived: { name: string; init: ts.Node }[] = [];
  const noteDerived = (n: ts.Node): void => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined) derived.push({ name: n.name.text, init: n.initializer });
    ts.forEachChild(n, noteDerived);
  };
  noteDerived(sf);
  const refersToOwner = (root: ts.Node): boolean => {
    let hit = false;
    const scan = (n: ts.Node): void => {
      if (hit) return;
      if (ts.isIdentifier(n) && ownerLocal.has(n.text)) hit = true;
      else if (!ts.isArrowFunction(n) && !ts.isFunctionExpression(n)) ts.forEachChild(n, scan);
    };
    scan(root);
    return hit;
  };
  for (let grew = ownerLocal.size > 0; grew; ) {
    grew = false;
    for (const d of derived) if (!ownerLocal.has(d.name) && refersToOwner(d.init)) (ownerLocal.add(d.name), (grew = true));
  }
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
  const props = new Map([...external, ...numericPropsIn(text)]);
  const strip = stripExpr;
  const MOTION_PROP = /^(transition|animation|transitionDuration|animationDuration|transitionDelay|animationDelay)$/;
  /** An inline motion property SET to something other than a clearing value. */
  const setsMotionAt = (n: ts.Node): boolean => {
    const isSet =
      (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isPropertyAccessExpression(n.left) && MOTION_PROP.test(n.left.name.text)) ||
      (ts.isPropertyAssignment(n) && (ts.isIdentifier(n.name) || ts.isStringLiteral(n.name)) && MOTION_PROP.test(n.name.text));
    if (!isSet) return false;
    const value = ts.isBinaryExpression(n) ? n.right : (n as ts.PropertyAssignment).initializer;
    return !(ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value)) || !/^(|none)$/.test(value.text.trim());
  };
  /* DELAYED STARTS. A local function "starts motion" when its body sets an inline motion property or
     calls (by name) a local function that does — to a fixed point, so `setTimeout(once, …)` where
     `once` calls `start` and `start` sets the transition is found. By name within the file: two
     same-named locals over-approximate (more timers inventoried, never fewer). */
  const bodies = new Map<string, ts.Node[]>();
  const noteFn = (n: ts.Node): void => {
    if (ts.isFunctionDeclaration(n) && n.name !== undefined && n.body !== undefined) bodies.set(n.name.text, [...(bodies.get(n.name.text) ?? []), n.body]);
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined) {
      const init = strip(n.initializer);
      if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) bodies.set(n.name.text, [...(bodies.get(n.name.text) ?? []), init.body]);
    }
    ts.forEachChild(n, noteFn);
  };
  noteFn(sf);
  const starters = new Set<string>();
  const startsMotion = (root: ts.Node): boolean => {
    let hit = false;
    const scan = (n: ts.Node): void => {
      if (hit) return;
      if (setsMotionAt(n)) hit = true;
      else if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && starters.has(n.expression.text)) hit = true;
      else if (ts.isIdentifier(n) && ownerLocal.has(n.text)) hit = true;
      else ts.forEachChild(n, scan);
    };
    scan(root);
    return hit;
  };
  for (let grew = true; grew; ) {
    grew = false;
    for (const [name, bs] of bodies) if (!starters.has(name) && bs.some(startsMotion)) (starters.add(name), (grew = true));
  }
  const isTimer = (e: ts.Expression): boolean =>
    (ts.isIdentifier(e) && e.text === "setTimeout") || (ts.isPropertyAccessExpression(e) && e.name.text === "setTimeout");
  const visit = (n: ts.Node): void => {
    // A delayed start: `setTimeout(cb, delay)` whose callback starts motion.
    if (ts.isCallExpression(n) && isTimer(n.expression) && n.arguments.length >= 2) {
      const cb = strip(n.arguments[0]!);
      const starts = ts.isIdentifier(cb) ? starters.has(cb.text) : (ts.isArrowFunction(cb) || ts.isFunctionExpression(cb)) && startsMotion(cb.body);
      if (starts) {
        const d = strip(n.arguments[1]!);
        const name = d.getText(sf);
        const value = ts.isNumericLiteral(d)
          ? Number(d.text)
          : ts.isIdentifier(d)
            ? consts.get(d.text)
            : ts.isPropertyAccessExpression(d)
              ? props.get(name)
              : undefined;
        if (value === undefined) unresolved.push(`${file}:${lineOf(n)} ${n.getText(sf).replace(/\s+/g, " ").slice(0, 100)}`);
        /* A 0 ms timer defers a task; it holds nothing on screen. */ else if (value > 0) found.push({ file, line: lineOf(n), name, kind: "delay", value });
      }
    }
    // A progress fraction: `something / X_MS`.
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.SlashToken) {
      const r = strip(n.right);
      if (ts.isIdentifier(r) && /^[A-Z][A-Z0-9_]*_MS$/.test(r.text)) {
        found.push({ file, line: lineOf(n), name: r.text, kind: "progress", value: consts.get(r.text) });
      }
    }
    // A stepped ease's duration: `{ …, durationMs: X_MS, … }` (an EaseSpec: the render loop runs it).
    if (ts.isPropertyAssignment(n) && (ts.isIdentifier(n.name) || ts.isStringLiteral(n.name)) && n.name.text === "durationMs") {
      const d = strip(n.initializer);
      if (ts.isIdentifier(d) && /^[A-Z][A-Z0-9_]*_MS$/.test(d.text)) found.push({ file, line: lineOf(n), name: d.text, kind: "ease", value: consts.get(d.text) });
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

const scriptFiles = files.filter((f) => /\.tsx?$/.test(f));
/** Every numeric property of every object-literal constant in src/, for delays spelled `X.prop`. */
const treeProps = new Map(scriptFiles.flatMap((f) => [...numericPropsIn(readFileSync(f, "utf8"))]));
const OWNER_STARTERS = easeOwnerStarters(readFileSync(resolve(PKG, EASE_OWNER), "utf8"));
const scriptScan = scriptFiles.map((f) => scriptMotionIn(rel(f), readFileSync(f, "utf8"), treeProps, OWNER_STARTERS));
const scriptMotion: ScriptMotion[] = [
  ...scriptScan.flatMap((s) => s.found),
  // The eases the fabric steps (their divisor is `spec.durationMs`, so they are read from the owner).
  ...OWNER_EASES.map((e) => ({ file: "src/fabric3d/emphasis.ts", line: 0, name: e.name, kind: "ease" as const, value: e.durationMs })),
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
  const spec = OWNER_EASES.find((e) => e.name === name);
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

  it("the script scan finds a DELAYED start — a timer whose callback starts a transition — and resolves its delay", () => {
    /* Acceptance report 2026-09-23 (C6): "The tier step-down hold has no §4.8 bound." The hold is the
       wait before an inline fade starts, and the scan saw only the fade: a timer that starts motion is
       found by what its callback DOES (directly, or through the local functions it calls), its delay
       resolved through local constants or an exported object's numeric property. */
    const { found, unresolved } = scriptMotionIn(
      "planted-delay.ts",
      [
        "const FADE_MS = 120;",
        "export function f(el: HTMLElement, a: number) {",
        "  const start = (): void => { el.style.transition = `opacity ${FADE_MS}ms linear`; };",
        "  const once = (): void => start();",
        "  setTimeout(once, HOLD.maxHoldMs);",
        "  window.setTimeout(() => once(), 90);",
        "  setTimeout(start, 0);",
        "  setTimeout(() => el.remove(), 5000);",
        "  setTimeout(once, a + 1);",
        "}",
      ].join("\n"),
      new Map([["HOLD.maxHoldMs", 1200]]),
    );
    expect(found.filter((f) => f.kind === "delay").map((f) => [f.name, f.value])).toEqual([
      ["HOLD.maxHoldMs", 1200],
      ["90", 90],
    ]);
    expect(unresolved.map((u) => u.split(" ")[0])).toEqual(["planted-delay.ts:9"]);
    expect(numericPropsIn("export const HOLD: Opts = { calmMs: 40, maxHoldMs: 1200 };\nconst A = Object.freeze({ b: 2, c: 'x' });")).toEqual(
      new Map([
        ["HOLD.calmMs", 40],
        ["HOLD.maxHoldMs", 1200],
        ["A.b", 2],
      ]),
    );
  });

  it("the script scan finds a script-STEPPED fade: its spec's duration, and a timer that starts it through the ease owner (C5, 2026-09-26)", () => {
    /* The tier cross-fade stopped being an inline CSS transition (it is stepped per frame by the ease
       owner's `stepTierFade`, capped per frame). Before this rule, that change made the scan lose the
       fade's 280 ms AND the hold before it — the "walks the real …" and hold cases below went red on
       exactly that. Both are found here from what the code does, under a local alias too. */
    const starters = new Set(["createTierFade", "HOVER_EASE", "FADE_MS"]);
    const { found, unresolved } = scriptMotionIn(
      "src/fabric3d/planted-stepped.ts",
      [
        "import { createTierFade as begin, HOVER_EASE, stepEaseChannel } from \"./emphasis\";",
        "import { createTierFade as elsewhere } from \"./not-the-owner\";",
        "const SLIDE_MS = 90;",
        "export const SLIDE: EaseSpec = { name: \"SLIDE_MS\", durationMs: SLIDE_MS, curve: \"linear\" };",
        "export function f(fade: { ease: unknown }, ch: EaseChannel) {",
        "  const start = (): void => { fade.ease = begin(); };",
        "  const once = (): void => start();",
        "  setTimeout(once, 700);",
        "  setTimeout(() => stepEaseChannel(ch, HOVER_EASE, 1, 16), 50);",
        "  setTimeout(() => { fade.ease = elsewhere(); }, 900);",
        "  setTimeout(() => stepEaseChannel(ch, SLIDE, 1, 16), 400);",
        // R4-VR1-4: a fade run through a VALUE the owner built (a slot, then its hold's handle).
        "  const slot = begin();",
        "  const handle = slot.presented(false);",
        "  const go = (): void => handle.start();",
        "  setTimeout(go, 1200);",
        "  const other = elsewhere();",
        "  setTimeout(() => other.start(), 300);",
        "}",
      ].join("\n"),
      new Map(),
      starters,
    );
    expect(found.map((x) => [x.name, x.kind, x.value])).toEqual([
      ["SLIDE_MS", "ease", 90],
      ["700", "delay", 700],
      ["50", "delay", 50],
      ["1200", "delay", 1200],
    ]);
    expect(unresolved).toEqual([]);
  });

  it("the ease owner's starters are derived from its source: what defines or runs a fade, and nothing else", () => {
    expect([...OWNER_STARTERS].sort()).toEqual(
      expect.arrayContaining(["createTierFade", "createTierFadeDriver", "stepTierFade", "stepEmphasis", "TIER_FADE_EASE", "TIER_FADE_MS", "RECEDE_EASE", "HOVER_EASE", "SELECT_EASE", "EASES"]),
    );
    for (const inert of ["isConverged", "createEmphasisState", "markEmphasisDirty", "LABEL_DROP_EVERY_FRAMES", "RECEDE_DEPTH", "FADE_MAX_STEP"]) {
      expect(OWNER_STARTERS.has(inert), `${inert} runs no fade`).toBe(false);
    }
    // A planted owner: a new fade defined through a new duration is found without editing this test.
    const planted = easeOwnerStarters(
      [
        "const WIPE_MS = 120;",
        "export const WIPE: EaseSpec = { name: \"WIPE_MS\", durationMs: WIPE_MS, curve: \"linear\" };",
        "function helper() { return WIPE; }",
        "export function startWipe() { return helper(); }",
        "export function unrelated() { return 3; }",
        // A fade run through a class's method (the tier-fade slot's shape, P3C-V2-2), reached through its factory.
        "class Wiper { go() { return WIPE; } }",
        "export function createWiper() { return new Wiper(); }",
        "export class Idle { n() { return 1; } }",
      ].join("\n"),
    );
    expect([...planted].sort()).toEqual(["WIPE", "createWiper", "startWipe"]);
    expect(OWNER_STARTERS.has("createTierFadeSlot"), "the slot's factory starts the tier fade").toBe(true);
  });

  it("walks the real stylesheets and scripts, and finds the motion they carry", () => {
    expect(stylesheets.length, "the walk found the stylesheets").toBeGreaterThan(3);
    expect(stylesheets.map(rel)).toContain("src/core/tokens.css");
    expect(TOKENS.get("--dur-instant")).toBe("80ms");
    expect(cssMotion.length, "CSS transitions/animations in the tree").toBeGreaterThan(10);
    expect(cssCollapse.length, "reduced-motion collapse declarations in the tree").toBeGreaterThan(0);
    expect([...scriptByName.keys()].sort()).toEqual(
      expect.arrayContaining(["CAMERA_TWEEN_MS", "DRAW_ON_MS", "PACKET_LOOP_MS", "TIER_FADE_MS", "TIER_FADE_HOLD_DEFAULTS.maxHoldMs", "dampingFactor"]),
    );
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
  /* Each class is matched as LITERAL text: every regex metacharacter is escaped (backslash included). A hyphen needs
     no escape outside a character class, so `a-b` matches as it did when only hyphens were escaped. */
  return classes.every((c) => new RegExp(`(^|[\\s"'\`{])${c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=[\\s"'\`}]|$)`, "m").test(markup));
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

/** The whole tree's text, read ONCE per file and counted (acceptance F2, W6 gate 2026-09-25): the
 *  reverse check re-read every source file on each of its calls — the tree read three times over
 *  inside the "is live" case, on a file a saturated clone spent 31 s on. */
let treeTextReads = 0;
let treeTextMemo: string | undefined;
const treeText = (): string => {
  if (treeTextMemo === undefined) {
    treeTextReads += 1;
    treeTextMemo = files.map((f) => readFileSync(f, "utf8")).join("\n");
  }
  return treeTextMemo;
};

/** Reverse: every row names something the code has, and states only times the code has for it. */
function reverseProblems(table: readonly Row[]): string[] {
  const cssBySelector = new Map<string, CssMotion[]>();
  for (const m of cssMotion) cssBySelector.set(m.selector, [...(cssBySelector.get(m.selector) ?? []), m]);
  const source = treeText();
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

  it("read the tree's text once for every reverse check above", () => {
    expect(treeTextReads, "the tree was read more than once").toBeLessThanOrEqual(1);
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

  it("a reduced-motion override that reaches descendants through `*` creates no transition (0 s, not 1 ms)", () => {
    /* D3 drawer pass: `.ev * { transition-duration: 1ms !important }` gave EVERY descendant — including
       ones that authored no transition, whose transition-property defaults to `all` — a 1 ms transition
       of the `visibility` they inherit. When the drawer opened, they read `hidden` for their first
       frame and focus() on them did nothing. A universal override must collapse to zero, never to a
       short non-zero time, so it cannot create a transition an element never declared. */
    const universal = cssCollapse.filter((m) => m.kind === "transition" && m.selector.includes("*"));
    expect(universal.length, "positive control: the tree has universal reduced-motion overrides").toBeGreaterThan(0);
    const creating = universal.filter((m) => m.times.some((t) => t > 0)).map((m) => `${m.file}:${m.line} ${m.selector} ${m.times.join("/")}`);
    expect(creating).toEqual([]);
  });

  it("every script-driven duration ends before 300 ms at 60 Hz, unless its row is exempt", () => {
    const problems: string[] = [];
    let judged = 0;
    for (const s of scriptByName.values()) {
      /* A `delay` is the wait BEFORE script-set motion starts — nothing moves during it — so it is
         held to the next test's rule, not to this one's; every motion the scan found before delays
         were discovered is judged here exactly as it was. */
      if (s.kind === "damping" || s.kind === "delay" || s.value === undefined) continue;
      judged += 1;
      if (s.value + FRAME_60 >= C6_BAR_MS && !EXEMPT.test(rowNaming(s.name)?.raw ?? "")) {
        problems.push(`${s.file}:${s.line} ${s.name} = ${s.value} ms can first show its end state at ${(s.value + FRAME_60).toFixed(1)} ms`);
      }
    }
    expect(problems).toEqual([]);
    expect(judged).toBeGreaterThan(3);
  });

  it("every hold before script-set motion is BOUNDED, and §4.8 states the bound the code has", () => {
    /* Acceptance report 2026-09-23 (C6): "The tier step-down hold has no §4.8 bound." A hold is not
       an animation, but a hold with no stated bound is how a frozen frame came to stand over a moving
       orbit for ~1,000 ms (C5). So each delay the scan finds must be on a row whose first bold
       duration is the code's own bound, and must say what happens under reduced motion; that the
       tier hold never holds over a camera move or a content change is pinned where the rule lives
       (src/fabric3d/stepdown.fadehold.test.ts). */
    const delays = [...scriptByName.values()].filter((s) => s.kind === "delay");
    expect(delays.map((d) => d.name), "the scan finds the tier-fade hold").toContain("TIER_FADE_HOLD_DEFAULTS.maxHoldMs");
    const problems: string[] = [];
    for (const d of delays) {
      const row = rowNaming(d.name);
      if (row === undefined) problems.push(`${d.file}:${d.line} ${d.name}: no §4.8 row states this hold's bound`);
      else if (boldTimesIn(row.cells[1] ?? "")[0] !== d.value) problems.push(`${d.file}:${d.line} ${d.name}: the row's bound is ${boldTimesIn(row.cells[1] ?? "")[0]} ms, the code's is ${d.value} ms`);
      if (row !== undefined && !/reduced motion/i.test(row.raw)) problems.push(`${d.file}:${d.line} ${d.name}: the row does not state its reduced-motion behaviour`);
    }
    expect(problems).toEqual([]);
    /* The rule is live: the same check over a table without the row names the hold. */
    const bare = rows.filter((r) => !r.names.includes("TIER_FADE_HOLD_DEFAULTS.maxHoldMs"));
    expect(scriptProblems(bare)).toContain(
      `${scriptByName.get("TIER_FADE_HOLD_DEFAULTS.maxHoldMs")!.file}:${scriptByName.get("TIER_FADE_HOLD_DEFAULTS.maxHoldMs")!.line} \`TIER_FADE_HOLD_DEFAULTS.maxHoldMs\`: no §4.8 row names it`,
    );
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

/* ── what STARTS the one loop (C6, independent refuter 2026-10-03) ──────────────────────────────
 *
 * Everything above pins the loop's WORDING and its bound. It never asked what starts it, and that is
 * where the inventory was false: a hop step (`]` / `[`, a hop-list row) re-sends the trace to the
 * scene, and the overlay re-armed the draw-on and all three packet loops on every re-send, while
 * flow.ts said a hop step "never re-runs the draw-on" and §4.8 said the packet "stops after 3 loops".
 * A reader stepping hops kept the bounded loop running indefinitely.
 *
 * The first repair (158a846) keyed "new" on the Trace OBJECT, and the round-2 refuter walked through
 * the door that left open: browser Back / Forward across a hop step reset the trace and re-traced the
 * same flow into a new object, which re-ran the draw-on and all three loops (15 s of motion from
 * alternating Back and Forward). An object test is the implementation's own definition of "the same
 * trace", so the tests that re-sent the identical object agreed with it by construction.
 *
 * So the trigger is pinned four ways: the inventory STATES it (both inventories, in words a reader
 * can check, history steps included); the code that ARMS motion is reachable only past the overlay's
 * same-PICTURE test, which compares content and never the object (found from the syntax tree, every
 * assignment that can switch the draw-on or the packet on, not a list of the ones seen); the scene's
 * camera framing is reachable only for a picture the overlay reports newly drawn; and BEHAVIOUR is
 * held elsewhere on the real producer's output — flow-triggers.test.ts (distinct objects of the same
 * answer owe no frame; every different path draws on) and src/app/history-hop-step.c6.test.tsx (the
 * real App's popstate handler never hands the fabric "no trace" or another object). */
describe("C6: the one loop's TRIGGER is the trigger the inventory states", () => {
  const FLOW = "src/fabric3d/flow.ts";
  const SCENE = "src/fabric3d/scene.ts";
  const parse = (f: string) => ts.createSourceFile(f, readFileSync(resolve(PKG, f), "utf8"), ts.ScriptTarget.Latest, true);
  /** The `setTrace` member of the object literal a file returns (the overlay / the scene handle). */
  function setTraceMethod(sf: ts.SourceFile): ts.MethodDeclaration[] {
    const out: ts.MethodDeclaration[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isMethodDeclaration(n) && n.name.getText(sf) === "setTrace" && n.body !== undefined) out.push(n);
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return out;
  }
  const packetRow = () => rowNaming("PACKET_LOOP_MS");
  const drawOnRow = () => rowNaming("DRAW_ON_MS");

  it("§4.8 states the trigger of the draw-on and the packet: a NEW picture, and neither a hop step nor Back / Forward re-runs either", () => {
    for (const row of [packetRow(), drawOnRow()]) {
      expect(row, "§4.8 has the row").toBeDefined();
      expect(row!.raw, `${row!.names[0]}: names its trigger`).toMatch(/\bnew picture\b/i);
      expect(row!.raw, `${row!.names[0]}: says the test is by content, not by object`).toMatch(/by content/i);
      expect(row!.raw, `${row!.names[0]}: says what a hop step does`).toMatch(/hop step[^|]*(re-runs|restarts) (neither|nothing|no)/i);
      expect(row!.raw, `${row!.names[0]}: says what browser Back / Forward across a hop step does`).toMatch(
        /Back[^|]*Forward[^|]*(re-runs|restarts) (neither|nothing|no)/i,
      );
      // The first repair's claim, false for Back / Forward: "a new object" is not what starts it.
      expect(row!.raw, `${row!.names[0]}: no object-identity trigger`).not.toMatch(/builds a new trace and runs once more/i);
    }
    // The row the refuter found stale: the packet IS exercised on the shipped snapshot (2-hop presets).
    expect(packetRow()!.raw).not.toMatch(/NOT OBSERVED|unexercisable/i);
  });

  it("flow.ts's own inventory states the same trigger, and claims no per-hop marker the code does not draw", () => {
    const header = readFileSync(resolve(PKG, FLOW), "utf8").split("*/")[0]!.replace(/\s*\*\s*/g, " ").replace(/\s+/g, " ");
    expect(header).toMatch(/TRIGGER both run once per NEW PICTURE/);
    expect(header).toMatch(/by content, not by object/);
    expect(header).toMatch(/browser Back \/ Forward across a hop step/);
    expect(header).toMatch(
      /by key, by row or through history — moves no marker, never re-runs the draw-on, never restarts or extends the loop, and never moves the camera/,
    );
    expect(header).not.toMatch(/explicit re-run makes a new trace object and so draws on/);
    // The old promise, never kept on screen: a "resting position" a hop step steered.
    expect(readFileSync(resolve(PKG, FLOW), "utf8")).not.toMatch(/resting position/);
  });

  it("every assignment that can switch the draw-on or the packet ON sits past setTrace's same-picture test", () => {
    const sf = parse(FLOW);
    const [method] = setTraceMethod(sf);
    expect(method, "flow.ts has a setTrace").toBeDefined();
    const body = method!.body!;
    /* The same-picture test: a top-level statement of the method that returns false when the key of
       what this trace would draw equals the key of what is drawn. */
    const guards = body.statements.filter(
      (st): st is ts.IfStatement =>
        ts.isIfStatement(st) && /\bdrawnKey\b/.test(st.expression.getText(sf)) && /return false/.test(st.thenStatement.getText(sf)),
    );
    expect(guards, "setTrace has exactly one same-picture test").toHaveLength(1);
    const guard = guards[0]!;
    const keyName = /^(\w+) === drawnKey$/.exec(guard.expression.getText(sf))?.[1];
    expect(keyName, "the test compares a key with the drawn key").toBeDefined();
    /* The key is the picture's CONTENT, built from the trace it is handed — never the object. */
    const keyDecl = body.statements.find(
      (st) => ts.isVariableStatement(st) && st.declarationList.declarations.some((d) => d.name.getText(sf) === keyName),
    );
    expect(keyDecl?.getText(sf) ?? "", "the key is pictureKeyOf(trace, ...)").toMatch(new RegExp(`const ${keyName} = pictureKeyOf\\(trace,`));
    expect(body.getText(sf), "no object-identity test of the trace in setTrace").not.toMatch(/\btrace (===|!==) (drawn|last|prev)\w*/);
    expect(readFileSync(resolve(PKG, FLOW), "utf8"), "no object-held 'drawn trace' left to compare against").not.toMatch(
      /\bdrawnTrace\b|\bdrawnSource\b/,
    );
    /* The class, from the tree: every write to a motion-arming flag or its start time, anywhere in the
       file. A write of the literal `false` disarms; anything else can arm, and may only happen inside
       setTrace past the guard — or, for the start times, inside update() where a running run is
       stamped, never restarted (`if (x === 0) x = nowMs`). */
    const ARMING = new Set(["revealing", "packetRunning", "revealStart", "packetStart"]);
    const arming: { name: string; where: string; pos: number; text: string }[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isIdentifier(n.left) && ARMING.has(n.left.text)) {
        if (n.right.kind !== ts.SyntaxKind.FalseKeyword) {
          let owner: ts.Node | undefined = n.parent;
          while (owner !== undefined && !ts.isMethodDeclaration(owner)) owner = owner.parent;
          arming.push({ name: n.left.text, where: owner === undefined ? "<module>" : owner.name.getText(sf), pos: n.getStart(sf), text: n.getText(sf) });
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    expect(arming.length, "the scan finds the arming writes (it is not vacuous)").toBeGreaterThanOrEqual(4);
    const bad = arming.filter((a) => {
      if (a.where === "setTrace") return a.pos <= guard.getEnd();
      if (a.where === "update") return !/^(revealStart|packetStart) = nowMs$/.test(a.text);
      return true;
    });
    expect(bad.map((a) => `${a.where}: ${a.text}`), "a write that can start motion outside a new trace").toEqual([]);
    /* The update() stamps start a run only once: each is guarded by `=== 0`, which setTrace alone resets. */
    const flowText = readFileSync(resolve(PKG, FLOW), "utf8");
    expect(flowText).toMatch(/if \(revealStart === 0\) revealStart = nowMs;/);
    expect(flowText).toMatch(/if \(packetStart === 0\) packetStart = nowMs;/);
  });

  it("the overlay takes no hop: nothing it draws can depend on which hop is active", () => {
    const [method] = setTraceMethod(parse(FLOW));
    expect(method!.parameters.map((p) => p.name.getText())).toEqual(["trace", "source"]);
  });

  it("scene.ts frames the camera, and re-derives emphasis, only for a picture the overlay reports newly drawn", () => {
    const sf = parse(SCENE);
    const methods = setTraceMethod(sf);
    expect(methods).toHaveLength(1);
    const body = methods[0]!.body!;
    const text = body.getText(sf);
    // The overlay's answer is bound, and an early return on "not newly drawn" precedes every effect.
    const call = /const (\w+) = flow\.setTrace\(next, traceSource\);/.exec(text);
    expect(call, "scene.setTrace binds the overlay's new-picture answer").not.toBeNull();
    const flag = call![1]!;
    const callAt = body.statements.findIndex((st) => st.getText(sf).startsWith(`const ${flag} = flow.setTrace(`));
    const early = body.statements[callAt + 1];
    expect(early !== undefined && ts.isIfStatement(early), "the statement after the overlay call is the early return").toBe(true);
    /* Not newly drawn and a trace WITH hops: the overlay already shows this picture, whatever object
       carries it — the scene does not ask whether it is the same object. A zero-hop trace draws no
       picture, so only for it may the object decide. */
    expect((early as ts.IfStatement).expression.getText(sf)).toBe(`!${flag} && next !== null && (next.hops.length > 0 || next === trace)`);
    const then = (early as ts.IfStatement).thenStatement.getText(sf).replace(/\s+/g, " ");
    expect(then, "the early branch only records the trace and returns").toBe("{ trace = next; return; }");
    const before = body.statements.slice(0, callAt + 2).map((st) => st.getText(sf)).join("\n");
    const after = body.statements.slice(callAt + 2).map((st) => st.getText(sf)).join("\n");
    for (const effect of ["cameraRig.moveTo(", "recomputeEmphasis(", "markEmphasisDirty(", "post.setBloomObjects("]) {
      expect(after.includes(effect), `${effect} comes after the early return`).toBe(true);
      expect(before.includes(effect), `${effect} before or inside the early return`).toBe(false);
    }
    // The hop parameter reaches nothing: a hop step cannot change the picture through this method.
    const hopParam = methods[0]!.parameters[1]!.name.getText(sf);
    expect(hopParam.startsWith("_"), "the hop parameter is declared unused").toBe(true);
    expect(text.includes(hopParam)).toBe(false);
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
 * for it, read from the brief itself. (`EASE_OWNER` is declared with the script scan above.)
 */

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

  /* One source file per case (acceptance F2, W6 gate 2026-09-25): this was one whole-tree parse in a
     single test. Each file is still parsed exactly once. */
  const easeScanned = files.filter((f) => /\.tsx?$/.test(f) && rel(f) !== EASE_OWNER);
  it("the ease scan's denominator is the tree's scripts, less only the owner", () => {
    expect(scriptFiles.map(rel)).toContain(EASE_OWNER);
    expect(easeScanned.length).toBe(scriptFiles.length - 1);
  });
  for (const f of easeScanned) {
    it(`${rel(f)} steps no exponential ease (only ${EASE_OWNER} may own one)`, () => {
      expect(findExponentialSteps(f, readFileSync(f, "utf8")), "a per-frame exponential ease outside src/fabric3d/emphasis.ts").toEqual([]);
    });
  }

  it("the ease owner itself steps no exponential ease either: every ease there is finite", () => {
    const own = findExponentialSteps(EASE_OWNER, readFileSync(resolve(PKG, EASE_OWNER), "utf8"));
    expect(own, "the owner still carries an exponential step").toEqual([]);
  });
});

describe("§4.8 states, for every ease the owner exports, the settle time the ease actually has", () => {
  /** 60 fps, the display rate §4.8's settle figures are stated at. */
  const DT = 1000 / 60;
  /** Step one ease 0 -> 1 at 60 fps; the time of the first frame whose value IS the target. */
  const settleMs = (spec: EaseSpec, reduced = false): number => {
    const ch = createEaseChannel(0);
    for (let frames = 1; frames <= 10_000; frames += 1) {
      stepEaseChannel(ch, spec, 1, DT, reduced);
      if (ch.value === 1) return frames * DT;
    }
    return Infinity;
  };
  const rowOf = (name: string): string | undefined =>
    s48.split("\n").find((l) => l.startsWith("|") && l.includes("`" + name + "`"));

  /* A row that states its duration but no settle figure yet, named with its reason. This is a ratchet,
     ENFORCED by the test below: it never holds a name outside its baseline ({TIER_FADE_MS}, 2026-09-26)
     and an entry whose row states the figure fails until it is removed. TIER_FADE_MS left it on
     2026-09-27 (C5-R2-4): the record step's §4.8 row now states "settles in **283.4 ms** at 60 fps",
     so the exact check covers it like every other ease. Empty is the ratchet's floor. */
  const SETTLE_FIGURE_PENDING = new Set<string>();
  /** What this block iterates: every ease the owner exports. */
  const SETTLE_CHECKED: readonly EaseSpec[] = OWNER_EASES;

  it("the owner exports the eases the fabric steps (the check is not vacuous)", () => {
    expect(EASES.map((e) => e.name).sort()).toEqual(["HOVER_MS", "RECEDE_MS", "SELECT_MS"]);
  });

  it("SETTLE_FIGURE_PENDING is an enforced ratchet: it never grows past its baseline, and an entry whose row now states the figure must go", () => {
    /* C5-R2-4 (verifier round 2): the set was documented "it may only shrink", but nothing stopped it
       growing, and nothing made a satisfied entry leave. The baseline is the set as it was introduced
       (2026-09-26); an entry may only ever be removed. Once §4.8 states a pending ease's settle figure,
       the entry is stale — the exact check above already covers it — and it fails here until removed. */
    const BASELINE = new Set(["TIER_FADE_MS"]);
    for (const n of SETTLE_FIGURE_PENDING) expect(BASELINE.has(n), `${n} was added to the ratchet; it may only shrink`).toBe(true);
    expect(SETTLE_FIGURE_PENDING.size).toBeLessThanOrEqual(BASELINE.size);
    const stale = [...SETTLE_FIGURE_PENDING].filter((n) => /settles in \*\*(\d+(?:\.\d+)?) ms\*\* at 60 fps/.test(rowOf(n) ?? ""));
    expect(stale, "pending entries whose §4.8 row already states the settle figure: remove them").toEqual([]);
  });

  it("the settle check's denominator is EVERY EaseSpec the owner exports, not the EASES list", () => {
    const declared = [...readFileSync(resolve(PKG, EASE_OWNER), "utf8").matchAll(/^export const (\w+): EaseSpec\b/gm)].map((m) => m[1]!);
    expect(declared.length, "the source parse found the owner's eases").toBeGreaterThan(0);
    expect(OWNER_EASE_EXPORTS.map(([k]) => k).sort(), "exports vs source").toEqual([...declared].sort());
    expect(SETTLE_CHECKED.map((e) => e.name).sort(), "the eases this block checks").toEqual(OWNER_EASES.map((e) => e.name).sort());
    expect(OWNER_EASES.map((e) => e.name), "the render loop's tier cross-fade is an owner ease").toContain("TIER_FADE_MS");
    for (const n of SETTLE_FIGURE_PENDING) expect(OWNER_EASES.map((e) => e.name), `pending entry ${n} names no owner ease`).toContain(n);
  });

  for (const spec of SETTLE_CHECKED) {
    it(`${spec.name}: the §4.8 row's duration is the ease's, and its stated settle time is the measured one`, () => {
      const row = rowOf(spec.name);
      expect(row, `§4.8 has no row naming \`${spec.name}\``).toBeDefined();
      const duration = /\*\*(\d+(?:\.\d+)?) ms\*\*/.exec(row!)?.[1];
      expect(Number(duration), `${spec.name}: the row's bold duration`).toBe(spec.durationMs);
      const stated = /settles in \*\*(\d+(?:\.\d+)?) ms\*\* at 60 fps/.exec(row!)?.[1];
      if (!SETTLE_FIGURE_PENDING.has(spec.name)) expect(stated, `${spec.name}: the row states "settles in **N ms** at 60 fps"`).toBeDefined();
      // Rounded to the microsecond: 15 frames of 1000/60 ms is 250.00000000000003 in doubles.
      const measured = Math.round(settleMs(spec) * 1000) / 1000;
      if (stated !== undefined) {
        // No later than stated, and stated no more than a millisecond of rounding above it.
        expect(measured, `${spec.name} settles at ${measured.toFixed(2)} ms, later than §4.8 states`).toBeLessThanOrEqual(Number(stated));
        expect(Number(stated) - measured, `${spec.name}: §4.8 overstates the settle time`).toBeLessThan(1);
      }
      /* Every ease lands on the first 60 fps frame at or after its duration: the frame its uncapped
         curve lands on. The cap binds on no landing frame (it does bind on the first four frames of
         HOVER_MS, RECEDE_MS and SELECT_MS; emphasis.test.ts measures where). */
      expect(measured, `${spec.name}: settles later than one frame after its duration`).toBeLessThan(spec.durationMs + DT + 1e-6);
      // And the C6 bar itself: under 300 ms.
      expect(measured).toBeLessThan(300);
      expect(row!, `${spec.name}: reduced-motion behaviour`).toMatch(/reduced motion/i);
    });

    it(`${spec.name}: under reduced motion the ease lands on its target in the frame it starts`, () => {
      expect(settleMs(spec, true)).toBe(DT);
    });
  }
});
