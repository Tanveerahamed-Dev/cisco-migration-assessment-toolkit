/**
 * focus-return.guard.test.ts — the STRUCTURAL guard for acceptance D3: nothing but
 * `src/app/focus-return.ts` decides where focus goes when a surface lets go of it.
 *
 * WHY A COMPILER AND NOT A GREP. The D3 regression was two lines: an `isConnected` check and an
 * else-arm that called `blur()`. Fixing the two sites the acceptance report named would leave the
 * class open — the next surface written with the same lines reintroduces it silently — and a grep
 * for `.blur()` both misses `el?.blur?.()` / `el["blur"]()` / `blur.call(el)` and cries wolf on
 * prose and strings. So every source file is compiled into ONE TypeScript program (the project's own
 * tsconfig, imports resolved, as `src/core/band-read.guard.test.ts` does) and six shapes are
 * rejected outside the owner:
 *
 *   1. `blur-call` — ANY call of a `blur` member. `blur()` never moves focus; it removes it, and the
 *      browser parks it on <body>.
 *   2. `isConnected-fallback` — a focus branch keyed on liveness (an `if`, a ternary or a statement
 *      `&&` whose condition reads `.isConnected`, directly or through a helper function whose body
 *      does) and whose taken arm calls `.focus()`, when its other arm does not call the owner. A
 *      missing else-arm counts: "if it is still there focus it, otherwise do nothing" is the same
 *      drop to <body> by omission.
 *   3. `captured-origin-focus` — `.focus()` called on a CAPTURED FOCUS ORIGIN: a value whose
 *      provenance, through variables, refs (`x.current`) and module state in the same file, is
 *      `document.activeElement` or a focus event's `relatedTarget`. That is what "return focus"
 *      is, whatever the variable is called — `back`, `returnTo`, `focusReturn`, `helpReturn` — and
 *      an unguarded `returnTo.current?.focus()` drops to <body> exactly as shape 2 does when the
 *      origin has unmounted. MEASURED: the Inspector's close (`focusReturn?.focus()`) is this shape
 *      and lands on BODY in the running build (review/audit-d3-focus.mjs); shapes 1 and 2 alone did
 *      not see it. Provenance is resolved by SYMBOL, not by name, so an unrelated `el` in another
 *      function is not tainted by this one's `const el = document.activeElement`.
 *   4. `hidden-without-release` — a JSX `hidden` or `inert` attribute on a DOM element whose value is
 *      decided at run time (anything but an absent value, `true`, `false` or a literal), in a
 *      component that never calls the owner's THIRD DOOR (`releaseFocusFrom` /
 *      `useReleaseFocusOnHide`). Such an element can stop being rendered while focus is inside it,
 *      and the browser then parks focus on <body> with no code of ours running at all. MEASURED
 *      (acceptance report D3, overturned PASS to FAIL, 2026-09-26): the evidence drawer and a
 *      resize to 900 px hid Rail B around its focused "Finding" radio, and shapes 1-3 could not see
 *      it because the close path ran no focus code. The ELEMENT is the unit: the hide is released only
 *      when the element carrying it passes its `ref` a value rooted at the same symbol as a third-door
 *      call's container (`useReleaseFocusOnHide(railRef, …)` with `ref={railRef}`;
 *      `releaseFocusFrom(panesRef.current[v], …)` with `ref={(el) => { panesRef.current.x = el; }}`).
 *      A door called in the same component for a different element does not count. WHAT THIS SHAPE CANNOT SEE:
 *      a hide made by a stylesheet keyed on some other attribute (the drawer's `data-drawer` ->
 *      `visibility: hidden` in shell.css). That one is declared to the owner explicitly (RailB's
 *      `closed`), and is measured, not parsed: `src/app/drawer-focus-return.test.tsx` and the
 *      drawer pass of `review/audit-d3-focus.mjs --sweep`.
 *   5. `ladder-render-without-layout-door` — a component (the outermost function around the site) that
 *      RENDERS from the viewport ladder — a JSX expression, or a conditional/`&&`/`if` that yields JSX,
 *      keyed on a value derived from the ladder owner's hooks (every exported `use*` function of
 *      src/app/surfaces.tsx — `useLadder`, `useRungIndex` — resolved by symbol, directly or through a
 *      hook declared in the same file, and through every variable initialised from one) —
 *      and never calls the owner's FOURTH DOOR (`useReleaseFocusOnLayoutChange`) with an argument
 *      derived from the ladder. Such a component mounts, unmounts or hides controls on a rung crossing,
 *      and a control holding focus as it goes leaves focus on <body> with no code of ours running.
 *      MEASURED (the independent verifier, D3-R2-1, release build): 11 of 74 tab stops lost to <body>
 *      across 7 rung crossings — the pane switch App.tsx mounts only below 1024 px, the header's More
 *      popover and inline toolbar (Header.tsx `useCompact`). Shape 4 could not see them: nothing
 *      carried `hidden`. WHAT THIS SHAPE CANNOT SEE: a ladder value handed to ANOTHER component as a
 *      prop (PaneSwitch's `showPanes`) is judged in the component that read the ladder, whose door
 *      covers the whole commit; a layout decided by measurement rather than by the ladder (the queue's
 *      View fold, a ResizeObserver) is declared to the door by its owner and measured, not parsed:
 *      `src/app/rung-focus-crossing.test.tsx` and the rung-crossing pass of
 *      `review/audit-d3-focus.mjs --sweep`, which focuses every tab stop at every rung and crosses to
 *      each neighbouring rung.
 *   6. `imperative-hide-without-release` — a write from SCRIPT whose DOM EFFECT leaves an element, or
 *      what is inside it, unrendered or detached — judged by the effect, not by a list of spellings
 *      (independent verifier R5-V2-4: the earlier list let seven of ten planted hides through): its
 *      `hidden`/`inert` state (property, attribute, namespaced attribute, toggle); a style that can stop
 *      rendering it (`display`, `visibility`, `content-visibility`) written as one property or as the whole
 *      style (`cssText`, the `style` attribute, `Object.assign(el.style, …)`) whose text may hold one; a
 *      popover hidden or a dialog closed; the element removed (`remove`, `replaceWith`, a parent's
 *      `removeChild`/`replaceChild`) or its contents replaced (`replaceChildren`, `innerHTML`,
 *      `textContent`, …). The receiver is an element by its TYPE; a value or name not knowable here may
 *      hide; a temporary the function itself created and never focused is not the class. It is released
 *      only by a third-door call on the element's own access path or an ANCESTOR of it (never a
 *      descendant, never merely the same variable). MEASURED (independent verifier R5-V2):
 *      FabricLabels.tsx hid a focused off-view pointer with `el.hidden = true` when a resize or a
 *      re-projection brought its device into view, and handed focus on with a bare `canvas.focus()`
 *      that never checked the canvas took it; shapes 4 and 5 parse only JSX attributes and
 *      ladder-keyed renders, so it passed both. WHAT THIS SHAPE CANNOT SEE: a hide made by a class or
 *      attribute a stylesheet keys on (`classList.add("is-hidden")`, `data-drawer`) — declared to the
 *      owner and measured in the browser, as for shape 4 — and a removal React performs (an unmount),
 *      which is the fourth door's.
 * Owner calls are resolved by symbol too (an aliased import still counts; a local function that
 * merely shares a name does not).
 *
 * THE DENOMINATOR IS THE TEST RUNNER'S OWN. The files scanned are derived from `vitest.config.ts`'s
 * `include` globs rather than a directory written here: every `.ts`/`.tsx` below the globs' root
 * that the runner does NOT treat as a test is source, and is scanned. A partition check asserts
 * that every file under that root is either a test or scanned, so the set cannot quietly narrow,
 * and a file that fails to parse is reported as UNSCANNED, never as clean.
 *
 * OFF-CLUSTER DEBT is listed in PENDING_ROUTING, keyed by file, shape and the normalised source of
 * the condition or call (not by line, which drifts). It is a ratchet, not an allowance: an entry
 * that no longer matches fails the suite until it is deleted, and a new violation anywhere is never
 * absorbed by it.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, matchesGlob, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { act, createElement, useRef, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import ts from "typescript";
import { afterEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { useReleaseFocusOnHide, useReleaseFocusOnLayoutChange } from "./focus-return";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OWNER = "src/app/focus-return.ts";
/** The viewport ladder's one owner (`useLadder`, LADDER_REM): shape 5's source of layout values. */
const LADDER_OWNER = "src/app/surfaces.tsx";
/** The owner's fourth door: a layout change that takes the focused element away. */
const LAYOUT_DOOR = "useReleaseFocusOnLayoutChange";

const toPosix = (p: string): string => p.split(sep).join("/");
const relOf = (abs: string): string => toPosix(relative(ROOT, abs));
const absOf = (rel: string): string => toPosix(join(ROOT, rel));

/* ── the denominator, from the runner's config ─────────────────────────────── */

/**
 * The `include` globs, read from vitest.config.ts by PARSING it (importing it would pull the whole
 * Vite config, plugins and all, into the test). Every string literal of the first `include`
 * array-literal property is a glob; a config this cannot read yields an empty list, which the first
 * test below rejects rather than scanning nothing and passing.
 */
function vitestIncludeGlobs(): string[] {
  const file = join(ROOT, "vitest.config.ts");
  const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.ES2023, true, ts.ScriptKind.TS);
  let globs: string[] | null = null;
  const visit = (n: ts.Node): void => {
    if (globs !== null) return;
    if (ts.isPropertyAssignment(n) && ts.isIdentifier(n.name) && n.name.text === "include" && ts.isArrayLiteralExpression(n.initializer)) {
      globs = n.initializer.elements.filter(ts.isStringLiteralLike).map((e) => e.text);
      return;
    }
    n.forEachChild(visit);
  };
  visit(sf);
  return globs ?? [];
}
const INCLUDE = vitestIncludeGlobs();

/** The static directory prefix of a glob: `src/**\/*.test.ts` → `src`. */
const globRoot = (g: string): string => {
  const parts = g.split("/");
  const i = parts.findIndex((p) => /[*?[{]/.test(p));
  return parts.slice(0, i < 0 ? parts.length - 1 : i).join("/");
};

const ROOTS = [...new Set(INCLUDE.map(globRoot))];
const EXTS = new Set(INCLUDE.map((g) => extname(g)));
const isTest = (rel: string): boolean => INCLUDE.some((g) => matchesGlob(rel, g));

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(relOf(p));
  }
  return out;
}

const ALL = ROOTS.flatMap((r) => walk(join(ROOT, r)));
const CANDIDATES = ALL.filter((f) => EXTS.has(extname(f)) && !f.endsWith(".d.ts"));
const SOURCES = CANDIDATES.filter((f) => !isTest(f));

/* ── the stylesheets' RENDERING rules (shape 6: a hide made by a class or an attribute a stylesheet keys on) ──
   Independent verifier QH-V1-5: shape 6 saw a hide written as a style, an attribute or a removal, and not one
   written as a CLASS or a DATA ATTRIBUTE that a stylesheet keys a hide on (`classList.add`, `className =`,
   `dataset.x =`). Deciding those is the stylesheet's business, so the stylesheets are READ: every rule of every
   `.css` file under the scanned root whose declarations decide whether an element is rendered (`display`,
   `visibility`, `content-visibility`, or a custom property that one of them reads) is a RENDERING rule, and a
   write can hide through it when it changes an attribute that rule's selector keys on — a class, an id, or any
   attribute (`[data-x="y"]`, `[aria-expanded]`, …). A rule that SHOWS (`display: inline-flex` on a `[data-x="y"]`
   descendant) hides by being un-matched, so it counts too. Only a positive exact match is read for its value (a
   `[data-visible="false"] { visibility: hidden }` cannot match a write of "true"); a negation, another operator or
   a value not knowable here may hide. A selector whose subject is a pseudo-element (`::after`) styles no element
   that can hold focus. */
export interface RenderingRule {
  file: string;
  selector: string;
  /** A declaration here can stop an element rendering / can make one render. */
  hides: boolean;
  shows: boolean;
  /** Custom properties the rendering declarations read (`display: var(--x)`). */
  vars: string[];
  mentions: { kind: "class" | "id" | "attr"; name: string; op: string | null; value: string | null; negated: boolean }[];
}
const RENDERING_PROPS: Readonly<Record<string, ReadonlySet<string>>> = {
  display: new Set(["none"]),
  visibility: new Set(["hidden", "collapse"]),
  "content-visibility": new Set(["hidden"]),
};
const PSEUDO_ELEMENT = /::?(?:before|after|marker|placeholder|selection|backdrop|first-line|first-letter|file-selector-button|cue|grammar-error|spelling-error|target-text)\b/i;
/** Every rendering rule of a stylesheet's text (comments stripped; @media/@supports/@layer/@container bodies read; nested rules read). */
export function renderingRules(file: string, text: string): RenderingRule[] {
  const out: RenderingRule[] = [];
  const src = text.replace(/\/\*[\s\S]*?\*\//g, "");
  const topLevel = (body: string): string => {
    let depth = 0;
    let s = "";
    for (const ch of body) {
      if (ch === "{") depth += 1;
      else if (ch === "}") depth -= 1;
      else if (depth === 0) s += ch;
    }
    return s;
  };
  const splitTop = (s: string, sep: string): string[] => {
    const parts: string[] = [];
    let depth = 0;
    let cur = "";
    for (const ch of s) {
      if (ch === "(" || ch === "[") depth += 1;
      else if (ch === ")" || ch === "]") depth -= 1;
      if (ch === sep && depth === 0) {
        parts.push(cur);
        cur = "";
      } else cur += ch;
    }
    parts.push(cur);
    return parts;
  };
  const mentionsOf = (sel: string): RenderingRule["mentions"] => {
    const negatedRanges: [number, number][] = [];
    for (const m of sel.matchAll(/:not\(/g)) {
      let depth = 1;
      let j = m.index + m[0].length;
      while (j < sel.length && depth > 0) {
        if (sel[j] === "(") depth += 1;
        else if (sel[j] === ")") depth -= 1;
        j += 1;
      }
      negatedRanges.push([m.index, j]);
    }
    const negated = (i: number): boolean => negatedRanges.some(([a, b]) => i >= a && i < b);
    const ms: RenderingRule["mentions"] = [];
    /* Attribute tests first; their text is blanked so a value such as ".pdf" is not read as a class. */
    let rest = sel;
    for (const m of sel.matchAll(/\[\s*([\w-]+)\s*(?:([~|^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]+)))?\s*(?:[is])?\s*\]/g)) {
      ms.push({ kind: "attr", name: m[1]!.toLowerCase(), op: m[2] ?? null, value: m[3] ?? m[4] ?? m[5] ?? null, negated: negated(m.index) });
      rest = rest.slice(0, m.index) + " ".repeat(m[0].length) + rest.slice(m.index + m[0].length);
    }
    for (const m of rest.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) ms.push({ kind: "class", name: m[1]!, op: null, value: null, negated: negated(m.index) });
    for (const m of rest.matchAll(/#(-?[_a-zA-Z][\w-]*)/g)) ms.push({ kind: "id", name: m[1]!, op: null, value: null, negated: negated(m.index) });
    return ms;
  };
  const visit = (s: string): void => {
    let i = 0;
    while (i < s.length) {
      const open = s.indexOf("{", i);
      if (open < 0) return;
      let prelude = s.slice(i, open);
      const cut = Math.max(prelude.lastIndexOf(";"), prelude.lastIndexOf("}"));
      if (cut >= 0) prelude = prelude.slice(cut + 1);
      prelude = prelude.trim();
      let depth = 1;
      let j = open + 1;
      while (j < s.length && depth > 0) {
        if (s[j] === "{") depth += 1;
        else if (s[j] === "}") depth -= 1;
        j += 1;
      }
      const body = s.slice(open + 1, j - 1);
      if (prelude.startsWith("@")) {
        /* Conditional group rules hold rules; @keyframes, @font-face, @property, @page hold none that select. */
        if (/^@(?:media|supports|layer|container|scope|document|starting-style)\b/i.test(prelude)) visit(body);
      } else if (prelude !== "") {
        let hides = false;
        let shows = false;
        const vars: string[] = [];
        for (const decl of topLevel(body).split(";")) {
          const k = decl.indexOf(":");
          if (k < 0) continue;
          const prop = decl.slice(0, k).trim().toLowerCase();
          const value = decl.slice(k + 1).replace(/!important/i, "").trim().toLowerCase();
          if (!Object.hasOwn(RENDERING_PROPS, prop)) continue;
          const used = [...value.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]!);
          if (used.length > 0) {
            vars.push(...used);
            hides = true;
            shows = true;
          } else if (RENDERING_PROPS[prop]!.has(value)) hides = true;
          else shows = true;
        }
        if (hides || shows) {
          for (const sel of splitTop(prelude, ",")) {
            const selector = sel.trim();
            if (selector === "" || PSEUDO_ELEMENT.test(selector)) continue;
            out.push({ file, selector, hides, shows, vars, mentions: mentionsOf(selector) });
          }
        }
        if (body.includes("{")) visit(body); /* CSS nesting: nested rules are rules too */
      }
      i = j;
    }
  };
  visit(src);
  return out;
}
const STYLESHEETS = ALL.filter((f) => extname(f) === ".css");
let renderingCache: RenderingRule[] | null = null;
/** The rendering rules of every stylesheet under the scanned root (read once). */
const RENDERING = (): RenderingRule[] => (renderingCache ??= STYLESHEETS.flatMap((f) => renderingRules(f, readFileSync(absOf(f), "utf8"))));

/* ── the program ───────────────────────────────────────────────────────────── */

function compilerOptions(): ts.CompilerOptions {
  const cfg = ts.readConfigFile(join(ROOT, "tsconfig.json"), ts.sys.readFile);
  if (cfg.error) throw new Error(ts.flattenDiagnosticMessageText(cfg.error.messageText, "\n"));
  const parsed = ts.parseJsonConfigFileContent(cfg.config, ts.sys, ROOT);
  return { ...parsed.options, noEmit: true };
}

/** A program over `rels`, with any `virtual` files (planted counterexamples) served from memory. */
function makeProgram(rels: readonly string[], virtual: ReadonlyMap<string, string> = new Map()): ts.Program {
  const opts = compilerOptions();
  const host = ts.createCompilerHost(opts);
  const byAbs = new Map([...virtual].map(([rel, src]) => [absOf(rel), src]));
  const origGet = host.getSourceFile.bind(host);
  host.getSourceFile = (name, lang, onErr, create) => {
    const src = byAbs.get(toPosix(name));
    return src === undefined
      ? origGet(name, lang, onErr, create)
      : ts.createSourceFile(name, src, lang, true, name.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  };
  const origExists = host.fileExists.bind(host);
  host.fileExists = (name) => byAbs.has(toPosix(name)) || origExists(name);
  const origRead = host.readFile.bind(host);
  host.readFile = (name) => byAbs.get(toPosix(name)) ?? origRead(name);
  return ts.createProgram([...rels, ...virtual.keys()].map(absOf), opts, host);
}

/* ── the analysis ──────────────────────────────────────────────────────────── */

export interface Violation {
  file: string;
  line: number;
  kind:
    | "blur-call"
    | "isConnected-fallback"
    | "captured-origin-focus"
    | "hidden-without-release"
    | "ladder-render-without-layout-door"
    | "imperative-hide-without-release";
  /** Whitespace-normalised source of the offending call or condition. */
  text: string;
}

const norm = (s: string): string => s.replace(/\s+/g, " ").trim();

function strip(e: ts.Expression): ts.Expression {
  while (
    ts.isParenthesizedExpression(e) ||
    ts.isNonNullExpression(e) ||
    ts.isAsExpression(e) ||
    ts.isTypeAssertionExpression(e) ||
    ts.isSatisfiesExpression(e)
  ) {
    e = e.expression;
  }
  return e;
}

/** The member name a call targets: `a.blur()`, `a?.blur?.()`, `a["blur"]()`, `a.blur.call(x)`. */
function calledMember(call: ts.CallExpression): string | null {
  const callee = strip(call.expression);
  const nameOf = (e: ts.Expression): string | null => {
    if (ts.isPropertyAccessExpression(e)) return e.name.text;
    if (ts.isElementAccessExpression(e) && ts.isStringLiteralLike(e.argumentExpression)) return e.argumentExpression.text;
    return null;
  };
  const direct = nameOf(callee);
  if ((direct === "call" || direct === "apply") && (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee))) {
    return nameOf(strip(callee.expression)) ?? direct;
  }
  return direct;
}

const contains = (node: ts.Node | undefined, pred: (n: ts.Node) => boolean): boolean => {
  if (node === undefined) return false;
  let hit = false;
  const visit = (n: ts.Node): void => {
    if (hit) return;
    if (pred(n)) hit = true;
    else n.forEachChild(visit);
  };
  visit(node);
  return hit;
};

const readsIsConnected = (n: ts.Node): boolean =>
  (ts.isPropertyAccessExpression(n) && n.name.text === "isConnected") ||
  (ts.isElementAccessExpression(n) && ts.isStringLiteralLike(n.argumentExpression) && n.argumentExpression.text === "isConnected");
const callsFocus = (n: ts.Node): boolean => ts.isCallExpression(n) && calledMember(n) === "focus";
const isOrigin = (n: ts.Node): boolean =>
  ts.isPropertyAccessExpression(n) && (n.name.text === "activeElement" || n.name.text === "relatedTarget");

/** Analyse one source file of `program`. Exported so the planted counterexamples run the same code. */
export interface Analysis {
  violations: Violation[];
  parseError: string | null;
  /** Whether the file calls the owner anywhere (resolved by symbol). */
  ownerCalls: boolean;
  /** How many ladder-keyed render sites shape 5 inspected (its non-vacuity, from the real tree). */
  ladderSites: number;
  /** How many imperative hides shape 6 inspected (its non-vacuity, from the real tree). */
  imperativeHides: number;
}

export function analyseFile(program: ts.Program, rel: string, rules: readonly RenderingRule[] = RENDERING()): Analysis {
  const sf = program.getSourceFile(absOf(rel));
  if (sf === undefined) return { violations: [], parseError: "not in the program", ownerCalls: false, ladderSites: 0, imperativeHides: 0 };
  const diags = program.getSyntacticDiagnostics(sf);
  if (diags.length > 0) {
    const first = diags[0]!;
    const { line } = sf.getLineAndCharacterOfPosition(first.start ?? 0);
    return { violations: [], parseError: `line ${line + 1}: ${ts.flattenDiagnosticMessageText(first.messageText, " ")}`, ownerCalls: false, ladderSites: 0, imperativeHides: 0 };
  }
  if (rel === OWNER) return { violations: [], parseError: null, ownerCalls: false, ladderSites: 0, imperativeHides: 0 };
  const checker = program.getTypeChecker();
  const out: Violation[] = [];
  const lineOf = (n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;

  const resolved = (node: ts.Node): ts.Symbol | undefined => {
    let s = checker.getSymbolAtLocation(node);
    if (s !== undefined && (s.flags & ts.SymbolFlags.Alias) !== 0) s = checker.getAliasedSymbol(s);
    return s;
  };
  const calleeName = (call: ts.CallExpression): ts.Node => {
    const c = strip(call.expression);
    return ts.isPropertyAccessExpression(c) ? c.name : c;
  };
  const callsOwner = (n: ts.Node): boolean =>
    ts.isCallExpression(n) &&
    (resolved(calleeName(n))?.declarations ?? []).some((d) => relOf(d.getSourceFile().fileName) === OWNER);

  /* Liveness: `.isConnected` read directly, or inside the body of a function the condition calls. */
  const bodyOf = (d: ts.Declaration): ts.Node | undefined => {
    if (ts.isFunctionDeclaration(d) || ts.isMethodDeclaration(d) || ts.isFunctionExpression(d) || ts.isArrowFunction(d)) return d.body;
    if (ts.isVariableDeclaration(d) && d.initializer !== undefined) {
      const init = strip(d.initializer);
      if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) return init.body;
    }
    return undefined;
  };
  const readsLiveness = (n: ts.Node, depth = 0): boolean => {
    if (readsIsConnected(n)) return true;
    if (!ts.isCallExpression(n) || depth > 3) return false;
    const decls = resolved(calleeName(n))?.declarations ?? [];
    return decls.some((d) => {
      if (relOf(d.getSourceFile().fileName) === OWNER) return false;
      return contains(bodyOf(d), (m) => readsLiveness(m, depth + 1));
    });
  };

  /* ── shape 3's taint: captured focus origins, by symbol ── */
  const ids = new Map<ts.Symbol, number>();
  const symKey = (s: ts.Symbol): number => {
    let k = ids.get(s);
    if (k === undefined) {
      k = ids.size;
      ids.set(s, k);
    }
    return k;
  };
  const slotOf = (e0: ts.Node): string | null => {
    const e = ts.isExpression(e0) ? strip(e0) : e0;
    if (ts.isIdentifier(e)) {
      const s = checker.getSymbolAtLocation(e);
      return s === undefined ? null : `#${symKey(s)}`;
    }
    if (ts.isPropertyAccessExpression(e)) {
      const base = slotOf(e.expression);
      return base === null ? null : `${base}.${e.name.text}`;
    }
    return null;
  };
  /** The sub-expressions whose VALUE an expression can evaluate to (not its conditions or callees). */
  const valueSources = (e0: ts.Expression): ts.Expression[] => {
    const e = strip(e0);
    if (ts.isConditionalExpression(e)) return [...valueSources(e.whenTrue), ...valueSources(e.whenFalse)];
    if (ts.isBinaryExpression(e)) {
      const op = e.operatorToken.kind;
      if (op === ts.SyntaxKind.QuestionQuestionToken || op === ts.SyntaxKind.BarBarToken) return [...valueSources(e.left), ...valueSources(e.right)];
      if (op === ts.SyntaxKind.AmpersandAmpersandToken) return valueSources(e.right);
      if (op === ts.SyntaxKind.EqualsToken) return valueSources(e.right);
    }
    return [e];
  };
  const tainted = new Set<string>();
  const carriesOrigin = (e: ts.Expression): boolean =>
    valueSources(e).some((v) => {
      if (isOrigin(v)) return true;
      const slot = slotOf(v);
      return slot !== null && tainted.has(slot);
    });
  const assignments: { target: string; value: ts.Expression }[] = [];
  const collect = (n: ts.Node): void => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined) {
      const t = slotOf(n.name);
      if (t !== null) assignments.push({ target: t, value: n.initializer });
    } else if (ts.isBinaryExpression(n)) {
      const op = n.operatorToken.kind;
      if (op === ts.SyntaxKind.EqualsToken || op === ts.SyntaxKind.QuestionQuestionEqualsToken || op === ts.SyntaxKind.BarBarEqualsToken) {
        const t = slotOf(n.left);
        if (t !== null) assignments.push({ target: t, value: n.right });
      }
    }
    n.forEachChild(collect);
  };
  collect(sf);
  for (let changed = true; changed; ) {
    changed = false;
    for (const a of assignments) {
      if (!tainted.has(a.target) && carriesOrigin(a.value)) {
        tainted.add(a.target);
        changed = true;
      }
    }
  }

  /* ── shape 4: a state-driven hide on an element never handed to the third door ── */
  const THIRD_DOOR = new Set(["releaseFocusFrom", "useReleaseFocusOnHide"]);
  const callsThirdDoor = (n: ts.Node): boolean =>
    ts.isCallExpression(n) &&
    (resolved(calleeName(n))?.declarations ?? []).some(
      (d) => relOf(d.getSourceFile().fileName) === OWNER && ts.isFunctionDeclaration(d) && d.name !== undefined && THIRD_DOOR.has(d.name.text),
    );
  const HIDING_ATTRIBUTES = new Set(["hidden", "inert"]);
  const isConstant = (e: ts.Expression | undefined): boolean => {
    if (e === undefined) return true;
    const x = strip(e);
    return x.kind === ts.SyntaxKind.TrueKeyword || x.kind === ts.SyntaxKind.FalseKeyword || ts.isStringLiteralLike(x) || ts.isNumericLiteral(x);
  };
  /* The door is bound to an ELEMENT, not to a component: the container a door call names (its first
     argument — `ref`, `ref.current`, `panesRef.current[v.id]`) is reduced to the symbol it is rooted
     at, and a hide is released only when the element carrying it hands that same symbol its `ref`.
     A door called in the same component for some OTHER element releases nothing here. */
  const rootSymbol = (e: ts.Expression | undefined): ts.Symbol | undefined => {
    let x = e === undefined ? undefined : strip(e);
    while (x !== undefined && (ts.isPropertyAccessExpression(x) || ts.isElementAccessExpression(x))) x = strip(x.expression);
    return x !== undefined && ts.isIdentifier(x) ? resolved(x) : undefined;
  };
  const doorBound = new Set<ts.Symbol>();
  const collectDoors = (n: ts.Node): void => {
    if (callsThirdDoor(n) && ts.isCallExpression(n)) {
      const s = rootSymbol(n.arguments[0]);
      if (s !== undefined) doorBound.add(s);
    }
    n.forEachChild(collectDoors);
  };
  collectDoors(sf);
  const refIsDoorBound = (el: ts.JsxOpeningElement | ts.JsxSelfClosingElement): boolean => {
    const ref = el.attributes.properties.find((p) => ts.isJsxAttribute(p) && ts.isIdentifier(p.name) && p.name.text === "ref");
    return (
      ref !== undefined &&
      ts.isJsxAttribute(ref) &&
      contains(ref.initializer, (m) => ts.isIdentifier(m) && (() => {
        const s = resolved(m);
        return s !== undefined && doorBound.has(s);
      })())
    );
  };
  const flagHide = (attr: ts.JsxAttribute): void => {
    if (!ts.isIdentifier(attr.name) || !HIDING_ATTRIBUTES.has(attr.name.text)) return;
    const el = attr.parent.parent;
    if (!(ts.isJsxOpeningElement(el) || ts.isJsxSelfClosingElement(el))) return;
    /* A DOM element (lower-case tag); a component's `hidden` prop is judged where it reaches the DOM. */
    if (!ts.isIdentifier(el.tagName) || !/^[a-z]/.test(el.tagName.text)) return;
    const init = attr.initializer;
    if (init === undefined || ts.isStringLiteral(init)) return;
    if (ts.isJsxExpression(init) && isConstant(init.expression)) return;
    if (refIsDoorBound(el)) return;
    out.push({ file: rel, line: lineOf(attr), kind: "hidden-without-release", text: norm(attr.getText(sf)) });
  };

  const flagBranch = (cond: ts.Expression, taken: ts.Node | undefined, other: ts.Node | undefined, at: ts.Node): void => {
    if (!contains(cond, (m) => readsLiveness(m))) return;
    /* Either polarity: `if (el.isConnected) el.focus(); else …` and
       `if (!el.isConnected) …; else el.focus()` are the same decision. */
    const takenFocuses = contains(taken, callsFocus);
    if (!takenFocuses && !contains(other, callsFocus)) return;
    /* The fallback arm is the one that does NOT focus; it must hand the decision to the owner. */
    const fallbackArm = takenFocuses ? other : taken;
    if (contains(fallbackArm, callsOwner)) return;
    out.push({ file: rel, line: lineOf(at), kind: "isConnected-fallback", text: norm(cond.getText(sf)) });
  };

  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n)) {
      const member = calledMember(n);
      if (member === "blur") out.push({ file: rel, line: lineOf(n), kind: "blur-call", text: norm(n.getText(sf)) });
      if (member === "focus") {
        const callee = strip(n.expression);
        const receiver =
          ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee) ? strip(callee.expression) : null;
        const slot = receiver === null ? null : slotOf(receiver);
        if (receiver !== null && (isOrigin(receiver) || (slot !== null && tainted.has(slot)))) {
          out.push({ file: rel, line: lineOf(n), kind: "captured-origin-focus", text: norm(n.getText(sf)) });
        }
      }
    }
    if (ts.isJsxAttribute(n)) flagHide(n);
    if (ts.isIfStatement(n)) flagBranch(n.expression, n.thenStatement, n.elseStatement, n);
    else if (ts.isConditionalExpression(n)) flagBranch(n.condition, n.whenTrue, n.whenFalse, n);
    else if (
      ts.isBinaryExpression(n) &&
      n.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken &&
      !ts.isIfStatement(n.parent) &&
      !ts.isConditionalExpression(n.parent) &&
      !ts.isBinaryExpression(n.parent) &&
      !ts.isParenthesizedExpression(n.parent)
    ) {
      /* `el.isConnected && el.focus()` used as a statement or an arrow body: a focus branch with no
         other arm. (Inside an if/ternary condition it is part of that branch's condition instead.) */
      flagBranch(n.left, n.right, undefined, n);
    }
    n.forEachChild(visit);
  };
  visit(sf);

  /* ── shape 5: a render keyed on the ladder, in a component that never declares the layout door ── */
  const isFunctionLike = (n: ts.Node): boolean =>
    ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) || ts.isArrowFunction(n) || ts.isMethodDeclaration(n);
  const declaredAs = (s: ts.Symbol | undefined, file: string, name: string): boolean =>
    (s?.declarations ?? []).some((d) => relOf(d.getSourceFile().fileName) === file && ts.isFunctionDeclaration(d) && d.name?.text === name);
  /* The ladder's hooks: every hook the ladder's owner EXPORTS (`useLadder`, `useRungIndex`, and any
     added later — its public surface, not a list kept here), and every function of this file whose
     body calls one. */
  const isOwnerLadderHook = (s: ts.Symbol | undefined): boolean =>
    (s?.declarations ?? []).some(
      (d) =>
        relOf(d.getSourceFile().fileName) === LADDER_OWNER &&
        ts.isFunctionDeclaration(d) &&
        d.name !== undefined &&
        /^use[A-Z]/.test(d.name.text) &&
        (ts.getCombinedModifierFlags(d) & ts.ModifierFlags.Export) !== 0,
    );
  const ladderHooks = new Set<ts.Symbol>();
  const callsLadderHook = (n: ts.Node): boolean => {
    if (!ts.isCallExpression(n)) return false;
    const s = resolved(calleeName(n));
    return s !== undefined && (ladderHooks.has(s) || isOwnerLadderHook(s));
  };
  const localFunctions: { sym: ts.Symbol; body: ts.Node }[] = [];
  const collectFns = (n: ts.Node): void => {
    if (ts.isFunctionDeclaration(n) && n.name !== undefined && n.body !== undefined) {
      const sym = checker.getSymbolAtLocation(n.name);
      if (sym !== undefined) localFunctions.push({ sym, body: n.body });
    } else if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined) {
      const init = strip(n.initializer);
      const sym = checker.getSymbolAtLocation(n.name);
      if (sym !== undefined && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) localFunctions.push({ sym, body: init.body });
    }
    n.forEachChild(collectFns);
  };
  collectFns(sf);
  for (let changed = true; changed; ) {
    changed = false;
    for (const f of localFunctions) {
      if (!ladderHooks.has(f.sym) && contains(f.body, callsLadderHook)) {
        ladderHooks.add(f.sym);
        changed = true;
      }
    }
  }
  /* Ladder-derived values: every variable initialised from a ladder hook's call or from another. */
  const ladderValues = new Set<ts.Symbol>();
  const readsLadder = (n: ts.Node | undefined): boolean =>
    contains(n, (m) => {
      if (ts.isIdentifier(m)) {
        const s = resolved(m);
        if (s !== undefined && ladderValues.has(s)) return true;
      }
      return callsLadderHook(m);
    });
  const ladderDecls: ts.VariableDeclaration[] = [];
  const collectDecls = (n: ts.Node): void => {
    if (ts.isVariableDeclaration(n) && n.initializer !== undefined) {
      const init = strip(n.initializer);
      if (!ts.isArrowFunction(init) && !ts.isFunctionExpression(init)) ladderDecls.push(n);
    }
    n.forEachChild(collectDecls);
  };
  collectDecls(sf);
  const boundNames = (b: ts.BindingName): ts.Identifier[] =>
    ts.isIdentifier(b) ? [b] : b.elements.flatMap((e) => (ts.isOmittedExpression(e) ? [] : boundNames(e.name)));
  for (let changed = true; changed; ) {
    changed = false;
    for (const d of ladderDecls) {
      if (!readsLadder(d.initializer)) continue;
      for (const id of boundNames(d.name)) {
        const s = checker.getSymbolAtLocation(id);
        if (s !== undefined && !ladderValues.has(s)) {
          ladderValues.add(s);
          changed = true;
        }
      }
    }
  }
  const callsLayoutDoorOnLadder = (n: ts.Node): boolean =>
    ts.isCallExpression(n) && declaredAs(resolved(calleeName(n)), OWNER, LAYOUT_DOOR) && readsLadder(n.arguments[0]);
  const hasJsx = (n: ts.Node | undefined): boolean =>
    contains(n, (m) => ts.isJsxElement(m) || ts.isJsxSelfClosingElement(m) || ts.isJsxFragment(m));
  /** The component a site belongs to: the OUTERMOST function around it (a `.map` callback is not one). */
  const componentOf = (n: ts.Node): ts.Node | null => {
    let outer: ts.Node | null = null;
    for (let p: ts.Node | undefined = n.parent; p !== undefined; p = p.parent) if (isFunctionLike(p)) outer = p;
    return outer;
  };
  let ladderSites = 0;
  const siteVisit = (n: ts.Node, inJsxExpression: boolean): void => {
    const logical =
      ts.isBinaryExpression(n) &&
      (n.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken || n.operatorToken.kind === ts.SyntaxKind.BarBarToken);
    const site =
      (ts.isJsxExpression(n) && n.expression !== undefined && readsLadder(n.expression)) ||
      (!inJsxExpression && ts.isConditionalExpression(n) && readsLadder(n.condition) && hasJsx(n)) ||
      (!inJsxExpression && logical && ts.isBinaryExpression(n) && readsLadder(n.left) && hasJsx(n.right)) ||
      (ts.isIfStatement(n) && readsLadder(n.expression) && hasJsx(n));
    if (site) {
      ladderSites += 1;
      const component = componentOf(n);
      if (component !== null && !contains(component, callsLayoutDoorOnLadder)) {
        out.push({ file: rel, line: lineOf(n), kind: "ladder-render-without-layout-door", text: norm(n.getText(sf)).slice(0, 160) });
      }
    }
    n.forEachChild((c) => siteVisit(c, inJsxExpression || ts.isJsxExpression(n)));
  };
  siteVisit(sf, false);

  /* ── shape 6: an IMPERATIVE hide on an element never handed to the third door ──
     The class is the DOM EFFECT, not a spelling (independent verifier R5-V2-4: a list of spellings let
     seven of ten planted hides through). A write from script is in the class when it can leave an
     ELEMENT, or anything inside it, unrendered or detached:
       - HIDE: its `hidden`/`inert` state (property, attribute — plain, namespaced or toggled); a style
         that can stop rendering it (`display`, `visibility`, `content-visibility`), written as one
         property (`.style.x =`, `.style[k] =`, `setProperty`) or as the WHOLE style (`cssText`, the `style`
         attribute, `.style =`, `Object.assign(el.style, …)`) whose text may hold such a declaration; a
         popover hidden (`hidePopover`, `togglePopover` not forced open) or a dialog closed;
       - DETACH: the element removed (`remove`, `replaceWith`, a parent's `removeChild`/`replaceChild`), or
         its contents replaced (`replaceChildren`, `innerHTML`/`outerHTML`/`textContent`/`innerText`).
     A value this cannot read (a variable, a template with substitutions) may hide, so it is in the class.
     The receiver must be an ELEMENT by its type (a `classList.remove`, an IndexedDB `close()` or a text
     node's text is not), `any` counting as one. NOT in the class: a TEMPORARY — an element the enclosing
     function itself created (`createElement`, `createElementNS`, `cloneNode`) and never focused, which
     cannot be holding the reader's focus (a download anchor). THE DOOR is bound to the element's own
     access path, or to an ANCESTOR of it (`el.parentElement`, `el.closest(…)`: releasing a container
     releases everything inside it) — never to anything merely rooted at the same variable. */
  const HIDING_STYLES: Readonly<Record<string, ReadonlySet<string>>> = {
    display: new Set(["none"]),
    visibility: new Set(["hidden", "collapse"]),
    "content-visibility": new Set(["hidden"]),
  };
  /** The strings an expression can be, by its TYPE (a literal, a const bound to one, a union of them); null when not knowable. */
  const literalTexts = (e: ts.Expression): string[] | null => {
    const x = strip(e);
    if (ts.isStringLiteralLike(x)) return [x.text];
    const ty = checker.getTypeAtLocation(x);
    const parts = ty.isUnion() ? ty.types : [ty];
    return parts.every((p) => p.isStringLiteral()) ? parts.map((p) => (p as ts.StringLiteralType).value) : null;
  };
  /** `contentVisibility` / `content-visibility` / `--x` -> the CSS property name. */
  const cssName = (p: string): string => (p.startsWith("--") ? p : p.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`).toLowerCase());
  /** Can a whole-style TEXT hide? A literal is read for a hiding declaration; anything else may. */
  const styleTextMayHide = (e: ts.Expression | undefined): boolean => {
    if (e === undefined) return true;
    return valueSources(e).some((v0) => {
      const texts = literalTexts(v0);
      if (texts === null) return true;
      return texts.join(";").split(";").some((decl) => {
        const [p, ...rest] = decl.split(":");
        const prop = (p ?? "").trim().toLowerCase();
        return Object.hasOwn(HIDING_STYLES, prop) && HIDING_STYLES[prop]!.has(rest.join(":").replace(/!important/i, "").trim().toLowerCase());
      });
    });
  };
  /** Can a value written to ONE property hide? `false` cannot; for a style, a literal outside the hiding values cannot. */
  const mayHide = (value: ts.Expression | undefined, style: string | null): boolean => {
    if (value === undefined) return true;
    return valueSources(value).some((v0) => {
      const v = strip(v0);
      if (style === null) return v.kind !== ts.SyntaxKind.FalseKeyword;
      const texts = literalTexts(v);
      return texts === null || texts.some((s) => HIDING_STYLES[style]!.has(s.replace(/!important/i, "").trim().toLowerCase()));
    });
  };
  /** Can an OBJECT of styles hide (Object.assign(el.style, {...}))? Each known key is read; anything else may. */
  const styleObjectMayHide = (e: ts.Expression | undefined): boolean => {
    if (e === undefined) return true;
    const o = strip(e);
    if (!ts.isObjectLiteralExpression(o)) return true;
    return o.properties.some((p) => {
      if (!ts.isPropertyAssignment(p)) return true;
      const key = ts.isIdentifier(p.name) || ts.isStringLiteralLike(p.name) ? cssName(p.name.text) : null;
      if (key === null) return true;
      return Object.hasOwn(HIDING_STYLES, key) && mayHide(p.initializer, key);
    });
  };
  /** The property a member expression names: `a.b` -> "b", `a["b"]` -> "b"; a computed key -> "" (unknown). */
  const memberName = (e: ts.Expression): string | null => {
    const x = strip(e);
    if (ts.isPropertyAccessExpression(x)) return x.name.text;
    if (ts.isElementAccessExpression(x)) return ts.isStringLiteralLike(x.argumentExpression) ? x.argumentExpression.text : "";
    return null;
  };
  const objectOf = (e: ts.Expression): ts.Expression | null => {
    const x = strip(e);
    return ts.isPropertyAccessExpression(x) || ts.isElementAccessExpression(x) ? x.expression : null;
  };
  /** `el.style` -> `el`: the element a style write hides. */
  const elementOfStyle = (e: ts.Expression | null): ts.Expression | null =>
    e !== null && memberName(e) === "style" ? objectOf(e) : null;
  /** Is this expression an ELEMENT by its type? (`any` / unknown: yes — fail closed.) */
  const isElement = (e: ts.Expression): boolean => {
    const t = checker.getNonNullableType(checker.getTypeAtLocation(e));
    if ((t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return true;
    const parts = t.isUnion() ? t.types : [t];
    return parts.some((p) => p.getProperty("tagName") !== undefined && p.getProperty("setAttribute") !== undefined);
  };
  const isDialogElement = (e: ts.Expression): boolean => {
    const t = checker.getNonNullableType(checker.getTypeAtLocation(e));
    if ((t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return true;
    const parts = t.isUnion() ? t.types : [t];
    return parts.some((p) => p.getProperty("showModal") !== undefined && p.getProperty("returnValue") !== undefined);
  };
  /** An access path: the root symbol, then each step (`.name`, `[literal]`, `[<expr>]`, `()` for a call). */
  const pathOf = (e0: ts.Expression): { root: ts.Symbol; steps: string[] } | null => {
    const steps: string[] = [];
    let x: ts.Expression = strip(e0);
    for (;;) {
      if (ts.isPropertyAccessExpression(x)) {
        steps.unshift(`.${x.name.text}`);
        x = strip(x.expression);
      } else if (ts.isElementAccessExpression(x)) {
        steps.unshift(`[${norm(x.argumentExpression.getText(sf))}]`);
        x = strip(x.expression);
      } else if (ts.isCallExpression(x) && (ts.isPropertyAccessExpression(strip(x.expression)) || ts.isElementAccessExpression(strip(x.expression)))) {
        const callee = strip(x.expression);
        steps.unshift(`.${memberName(callee) ?? ""}()`);
        x = strip((callee as ts.PropertyAccessExpression | ts.ElementAccessExpression).expression);
      } else break;
    }
    if (!ts.isIdentifier(x)) return null;
    const root = resolved(x);
    return root === undefined ? null : { root, steps };
  };
  /** Steps that go UP the tree: a door on `el.parentElement` releases everything inside it, `el` included. */
  const ANCESTOR_STEP = /^\.(parentElement|parentNode|offsetParent|closest\(\))$/;
  const doorPaths: { root: ts.Symbol; steps: string[] }[] = [];
  const collectDoorPaths = (n: ts.Node): void => {
    if (callsThirdDoor(n) && ts.isCallExpression(n) && n.arguments[0] !== undefined) {
      const p = pathOf(n.arguments[0]);
      if (p !== null) doorPaths.push(p);
    }
    n.forEachChild(collectDoorPaths);
  };
  collectDoorPaths(sf);
  /** Released: a door names this very path, or a path that climbs from it. */
  const released = (target: ts.Expression): boolean => {
    const p = pathOf(target);
    if (p === null) return false;
    return doorPaths.some(
      (d) =>
        d.root === p.root &&
        d.steps.length >= p.steps.length &&
        p.steps.every((s, i) => d.steps[i] === s) &&
        d.steps.slice(p.steps.length).every((s) => ANCESTOR_STEP.test(s)),
    );
  };
  /** The enclosing function of `n`, or the source file. */
  const scopeOf = (n: ts.Node): ts.Node => {
    for (let p: ts.Node | undefined = n.parent; p !== undefined; p = p.parent) if (isFunctionLike(p)) return p;
    return sf;
  };
  const CREATES = new Set(["createElement", "createElementNS", "cloneNode"]);
  /** A TEMPORARY: bound in this very function to a freshly created element, and never focused there. */
  const isTemporary = (target: ts.Expression, site: ts.Node): boolean => {
    const x = strip(target);
    if (!ts.isIdentifier(x)) return false;
    const s = resolved(x);
    const decl = s?.valueDeclaration;
    if (decl === undefined || !ts.isVariableDeclaration(decl) || decl.initializer === undefined) return false;
    const scope = scopeOf(site);
    if (scopeOf(decl) !== scope) return false;
    const init = strip(decl.initializer);
    if (!ts.isCallExpression(init) || !CREATES.has(calledMember(init) ?? "")) return false;
    return !contains(scope, (m) => {
      if (!ts.isCallExpression(m) || calledMember(m) !== "focus") return false;
      const callee = strip(m.expression);
      const recv = ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee) ? strip(callee.expression) : null;
      return recv !== null && ts.isIdentifier(recv) && resolved(recv) === s;
    });
  };
  /** The name of the function a site sits in, for a key that does not drift with lines. */
  const enclosingName = (n: ts.Node): string => {
    for (let p: ts.Node | undefined = n.parent; p !== undefined; p = p.parent) {
      if ((ts.isFunctionDeclaration(p) || ts.isMethodDeclaration(p)) && p.name !== undefined) return p.name.getText(sf);
      if ((ts.isArrowFunction(p) || ts.isFunctionExpression(p)) && ts.isVariableDeclaration(p.parent) && ts.isIdentifier(p.parent.name)) return p.parent.name.text;
    }
    return "(module)";
  };
  let imperativeHides = 0;
  /** A write whose element cannot be named here (a style object of unknown origin, a stylesheet): it may hide any
   *  element, no door can be bound to it, and it FAILS CLOSED. */
  const UNKNOWN_ELEMENT: unique symbol = Symbol("an element this cannot name");
  /** `target` is the element the write leaves unrendered or detached (or whose contents it detaches). */
  const flagImperative = (site: ts.Node, target: ts.Expression | typeof UNKNOWN_ELEMENT | null): void => {
    if (target === null) return;
    if (target !== UNKNOWN_ELEMENT && !isElement(target)) return;
    imperativeHides += 1;
    if (target !== UNKNOWN_ELEMENT && (released(target) || isTemporary(target, site))) return;
    out.push({ file: rel, line: lineOf(site), kind: "imperative-hide-without-release", text: `${enclosingName(site)}: ${norm(site.getText(sf))}` });
  };
  /* THE STYLE OBJECT, followed to its element (independent verifier QH-V1-5: `const s = el.style; s.display =
     "none"` went unseen). `el.style` -> `el`; a CONST bound to a style object -> that object's element; any other
     value typed as a CSSStyleDeclaration (a parameter, a `let`, a computed style) -> an element this cannot name,
     which fails closed. null: not a style object at all. */
  const isStyleDeclaration = (e: ts.Expression): boolean => {
    const t = checker.getNonNullableType(checker.getTypeAtLocation(e));
    if ((t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return false;
    const parts = t.isUnion() ? t.types : [t];
    return parts.some((p) => p.getProperty("cssText") !== undefined && p.getProperty("setProperty") !== undefined && p.getProperty("getPropertyValue") !== undefined);
  };
  const styleHost = (e: ts.Expression | null, seen: Set<ts.Node> = new Set()): ts.Expression | typeof UNKNOWN_ELEMENT | null => {
    if (e === null) return null;
    const x = strip(e);
    const viaStyle = elementOfStyle(x);
    if (viaStyle !== null) return viaStyle;
    if (!isStyleDeclaration(x)) return null;
    if (ts.isIdentifier(x)) {
      const d = resolved(x)?.valueDeclaration;
      if (d !== undefined && ts.isVariableDeclaration(d) && d.initializer !== undefined && !seen.has(d) && (ts.getCombinedNodeFlags(d) & ts.NodeFlags.Const) !== 0) {
        seen.add(d);
        return styleHost(d.initializer, seen);
      }
    }
    return UNKNOWN_ELEMENT;
  };
  /* CLASS AND ATTRIBUTE WRITES, judged by the stylesheets' rendering rules (RenderingRule, above). */
  /** Can ADDING (or removing, or either) these classes (null: not knowable) stop an element rendering through a rule?
   *  A class added matches the rules that name it and un-matches the `:not()`s that do; a removal the reverse. */
  const classWriteMayHide = (names: string[] | null, how: "add" | "remove" | "either" = "either"): boolean =>
    rules.some((r) =>
      r.mentions.some((m) => {
        if (m.kind !== "class" || (names !== null && !names.includes(m.name))) return false;
        const onAdd = (!m.negated && r.hides) || (m.negated && r.shows);
        const onRemove = (!m.negated && r.shows) || (m.negated && r.hides);
        return how === "add" ? onAdd : how === "remove" ? onRemove : onAdd || onRemove;
      }),
    );
  /** `className =` on an element this very function just created (it had no class to lose): the classes are ADDED. */
  const freshlyCreated = (target: ts.Expression): boolean => {
    const x = strip(target);
    if (!ts.isIdentifier(x)) return false;
    const decl = resolved(x)?.valueDeclaration;
    if (decl === undefined || !ts.isVariableDeclaration(decl) || decl.initializer === undefined) return false;
    const init = strip(decl.initializer);
    if (!ts.isCallExpression(init) || (calledMember(init) !== "createElement" && calledMember(init) !== "createElementNS")) return false;
    /* Created in the same function, and no OTHER class write to it there (one could have added a class this drops). */
    const scope = scopeOf(target);
    if (scopeOf(decl) !== scope) return false;
    const sym = resolved(x);
    const classWrites = (m: ts.Node): boolean => {
      const onSym = (e: ts.Expression | null): boolean => e !== null && ts.isIdentifier(strip(e)) && resolved(strip(e)) === sym;
      if (ts.isBinaryExpression(m) && m.operatorToken.kind === ts.SyntaxKind.EqualsToken) return memberName(m.left) === "className" && onSym(objectOf(m.left));
      if (ts.isCallExpression(m)) {
        const c = strip(m.expression);
        const recv = ts.isPropertyAccessExpression(c) || ts.isElementAccessExpression(c) ? objectOf(c) : null;
        return recv !== null && memberName(recv) === "classList" && onSym(objectOf(recv));
      }
      return false;
    };
    let count = 0;
    const walkScope = (m: ts.Node): void => {
      if (classWrites(m)) count += 1;
      m.forEachChild(walkScope);
    };
    walkScope(scope);
    return count <= 1;
  };
  const idWriteMayHide = (): boolean => rules.some((r) => r.mentions.some((m) => m.kind === "id"));
  /** Can setting (values: the strings it can be, null when not knowable) or REMOVING attribute `attr` (null: some
   *  `data-*` attribute this cannot name) stop an element rendering through a rendering rule? */
  const attrWriteMayHide = (attr: string | null, values: string[] | null, removal: boolean): boolean =>
    rules.some((r) =>
      r.mentions.some((m) => {
        if (m.kind !== "attr" || (attr === null ? !m.name.startsWith("data-") : m.name !== attr)) return false;
        if (removal || attr === null) return (!m.negated && r.shows) || (m.negated && r.hides) || attr === null;
        if (values === null || m.negated || (m.op !== null && m.op !== "=")) return true;
        if (m.op === null) return r.hides; /* present now: a presence test matches — it hides only if the rule does */
        return (values.includes(m.value ?? "") && r.hides) || (values.some((v) => v !== m.value) && r.shows);
      }),
    );
  /** The strings a value can be, or null when not knowable. */
  const valuesOf = (e: ts.Expression | undefined): string[] | null => {
    if (e === undefined) return null;
    const all: string[] = [];
    for (const v of valueSources(e)) {
      const t = literalTexts(v);
      if (t === null) return null;
      all.push(...t);
    }
    return all;
  };
  /** A generic attribute write: `name` known (lower-cased) — hidden/inert/style are judged by their own rules. */
  const judgeAttribute = (site: ts.Node, el: ts.Expression, name: string, values: string[] | null, removal: boolean): void => {
    if (name === "class") {
      /* The whole list replaced (or removed): any class it had may go. */
      if (classWriteMayHide(null, removal ? "remove" : "either")) flagImperative(site, el);
    } else if (name === "id") {
      if (idWriteMayHide()) flagImperative(site, el);
    } else if (name === "open") {
      /* A <details> or <dialog> that loses `open` hides its contents in every browser, whatever the stylesheets say. */
      if (removal || values === null || values.includes("false")) flagImperative(site, el);
    } else if (attrWriteMayHide(name, values, removal)) flagImperative(site, el);
  };
  /** `fooBar` (a dataset key) -> `data-foo-bar`. */
  const dataAttr = (key: string): string => `data-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
  /** Is this a CSSStyleSheet (a write to it can hide any element)? */
  const isStyleSheet = (e: ts.Expression): boolean => {
    const t = checker.getNonNullableType(checker.getTypeAtLocation(e));
    const parts = t.isUnion() ? t.types : [t];
    return parts.some((p) => p.getProperty("insertRule") !== undefined && p.getProperty("cssRules") !== undefined);
  };
  /** A custom property a rendering rule reads (`display: var(--x)`): writing it can hide. */
  const renderingVar = (name: string): boolean => rules.some((r) => r.vars.includes(name));
  const CONTENT_WRITES = new Set(["innerHTML", "outerHTML", "textContent", "innerText", "outerText"]);
  const HIDING_ATTRS = new Set(["hidden", "inert"]);
  const imperativeVisit = (n: ts.Node): void => {
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const name = memberName(n.left);
      const obj = objectOf(n.left);
      const styleOf = obj === null ? null : styleHost(obj);
      /* `el.dataset.x = v`, `el.classList.value = v`: the element is the object's object. */
      const owner = obj === null ? null : objectOf(obj);
      const via = obj === null ? null : memberName(obj);
      if (name !== null && obj !== null) {
        if (via === "dataset" && owner !== null) {
          if (name === "") {
            if (attrWriteMayHide(null, null, false)) flagImperative(n, owner);
          } else judgeAttribute(n, owner, dataAttr(name), valuesOf(n.right), false);
        } else if (via === "classList" && owner !== null && name === "value") {
          if (classWriteMayHide(null)) flagImperative(n, owner);
        } else if (name === "hidden" || name === "inert") {
          if (mayHide(n.right, null)) flagImperative(n, obj);
        } else if (CONTENT_WRITES.has(name)) flagImperative(n, obj);
        else if (name === "style") {
          /* `el.style = "…"`: the whole style. */
          if (styleTextMayHide(n.right)) flagImperative(n, obj);
        } else if (name === "className" && styleOf === null) {
          /* The whole list replaced: any class it had may go — unless this function just created it (it had none). */
          const names = valuesOf(n.right)?.flatMap((s) => s.split(/\s+/).filter((c) => c !== "")) ?? null;
          if (freshlyCreated(obj) ? classWriteMayHide(names, "add") : classWriteMayHide(null)) flagImperative(n, obj);
        } else if (name === "id" && styleOf === null) {
          if (idWriteMayHide()) flagImperative(n, obj);
        } else if (name === "open" && styleOf === null) {
          /* A <details> or <dialog> that loses `open` hides its contents, whatever the stylesheets say. */
          if (valueSources(n.right).some((v) => strip(v).kind !== ts.SyntaxKind.TrueKeyword)) flagImperative(n, obj);
        } else if (name === "adoptedStyleSheets") {
          flagImperative(n, UNKNOWN_ELEMENT);
        } else if (styleOf !== null) {
          /* `el.style.x = v`, `el.style["x"] = v`, `el.style[k] = v` (a key not known here may hide) — or the same
             through a style object bound elsewhere. */
          const prop = name === "" ? null : cssName(name);
          if (prop === "css-text") {
            if (styleTextMayHide(n.right)) flagImperative(n, styleOf);
          } else if (prop === null || (Object.hasOwn(HIDING_STYLES, prop) && mayHide(n.right, prop))) flagImperative(n, styleOf);
        }
      }
    } else if (ts.isDeleteExpression(n)) {
      /* `delete el.dataset.x`: the attribute removed. */
      const obj = objectOf(n.expression);
      const name = memberName(n.expression);
      if (obj !== null && memberName(obj) === "dataset" && objectOf(obj) !== null && name !== null) {
        if (name === "") {
          if (attrWriteMayHide(null, null, true)) flagImperative(n, objectOf(obj));
        } else judgeAttribute(n, objectOf(obj)!, dataAttr(name), null, true);
      }
    } else if (ts.isCallExpression(n)) {
      const member = calledMember(n);
      const callee = strip(n.expression);
      const obj = ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee) ? objectOf(callee) : null;
      /** The one name an argument can be (by its type); null when it is not one knowable string. */
      const lit = (a: ts.Expression | undefined): string | null => {
        const texts = a === undefined ? null : literalTexts(a);
        return texts !== null && texts.length === 1 ? texts[0]!.trim().toLowerCase() : null;
      };
      const args = n.arguments;
      /** A local name without its namespace prefix (`xlink:href` -> `href`). */
      const localName = (a: string): string => a.slice(a.indexOf(":") + 1);
      const via = obj === null ? null : memberName(obj);
      const owner = obj === null ? null : objectOf(obj);
      if (via === "classList" && owner !== null && (member === "add" || member === "remove" || member === "toggle" || member === "replace")) {
        /* A class added, removed, toggled or replaced: judged by the rendering rules that key on those classes
           (a name not knowable here may be any of them). `toggle`'s second argument is its force, not a class. */
        const named = member === "toggle" ? args.slice(0, 1) : args;
        let names: string[] | null = [];
        for (const a of named) {
          const t = ts.isSpreadElement(a) ? null : literalTexts(a);
          if (t === null) {
            names = null;
            break;
          }
          names.push(...t.flatMap((s) => s.split(/\s+/).filter((x) => x !== "")));
        }
        if (classWriteMayHide(names, member === "add" ? "add" : member === "remove" ? "remove" : "either")) flagImperative(n, owner);
      } else if (obj !== null && (member === "setAttribute" || member === "toggleAttribute" || member === "setAttributeNS")) {
        const nameArg = member === "setAttributeNS" ? args[1] : args[0];
        const valueArg = member === "setAttributeNS" ? args[2] : args[1];
        const attr0 = lit(nameArg);
        const attr = attr0 === null ? null : localName(attr0);
        if (attr === null) flagImperative(n, obj); /* an attribute this cannot read may be one of them */
        else if (HIDING_ATTRS.has(attr)) {
          if (member !== "toggleAttribute" || mayHide(valueArg, null)) flagImperative(n, obj);
        } else if (attr === "style") {
          if (member === "toggleAttribute" || styleTextMayHide(valueArg)) flagImperative(n, obj);
        } else if (member === "toggleAttribute") {
          /* Forced on: present (""); forced off: removed; not forced: either. */
          const force = valueArg === undefined ? undefined : strip(valueArg);
          if (force === undefined || force.kind !== ts.SyntaxKind.FalseKeyword) judgeAttribute(n, obj, attr, [""], false);
          if (force === undefined || force.kind !== ts.SyntaxKind.TrueKeyword) judgeAttribute(n, obj, attr, null, true);
        } else if (attr !== "open") judgeAttribute(n, obj, attr, valuesOf(valueArg), false); /* setting `open` shows */
      } else if (obj !== null && (member === "removeAttribute" || member === "removeAttributeNS")) {
        const attr0 = lit(member === "removeAttributeNS" ? args[1] : args[0]);
        const attr = attr0 === null ? null : localName(attr0);
        if (attr === null) flagImperative(n, obj);
        else if (attr === "style") flagImperative(n, obj); /* the inline style removed may have been what rendered it */
        else if (!HIDING_ATTRS.has(attr)) judgeAttribute(n, obj, attr, null, true); /* removing hidden/inert shows */
      } else if (obj !== null && (member === "setProperty" || member === "removeProperty")) {
        /* One property of a style object, set or removed. Removing a rendering property may un-override a stylesheet's
           hide (an inline `display: block` over a sheet's `none`); a custom property counts when a rendering rule reads it. */
        const prop = lit(args[0]);
        const styleEl = styleHost(obj);
        const may =
          prop === null ||
          (prop.startsWith("--") ? renderingVar(prop) : Object.hasOwn(HIDING_STYLES, prop) && (member === "removeProperty" || mayHide(args[1], prop)));
        if (styleEl !== null && may) flagImperative(n, styleEl);
      } else if (via === "attributeStyleMap" && owner !== null && (member === "set" || member === "append" || member === "delete" || member === "clear")) {
        /* The typed OM: a CSSStyleValue is not read here, so a rendering property set or deleted may hide. */
        const prop = member === "clear" ? null : lit(args[0]);
        if (prop === null || (prop.startsWith("--") ? renderingVar(prop) : Object.hasOwn(HIDING_STYLES, prop))) flagImperative(n, owner);
      } else if (obj !== null && /^(?:insertRule|deleteRule|addRule|removeRule|replace|replaceSync)$/.test(member ?? "") && isStyleSheet(obj)) {
        /* A stylesheet rewritten: any element may stop rendering, and no door can name them all. */
        flagImperative(n, UNKNOWN_ELEMENT);
      } else if (member === "assign" && args.length >= 2 && styleHost(strip(args[0]!)) !== null) {
        /* Object.assign(el.style, { … }) */
        if (args.slice(1).some((a) => styleObjectMayHide(a))) flagImperative(n, styleHost(strip(args[0]!)));
      } else if (obj !== null && (member === "remove" || member === "replaceWith") && args.length === (member === "remove" ? 0 : args.length)) {
        flagImperative(n, obj);
      } else if (obj !== null && member === "replaceChildren") {
        flagImperative(n, obj);
      } else if (obj !== null && member === "removeChild") {
        flagImperative(n, args[0] === undefined ? null : strip(args[0]));
      } else if (obj !== null && member === "replaceChild") {
        flagImperative(n, args[1] === undefined ? null : strip(args[1]));
      } else if (obj !== null && member === "hidePopover") {
        flagImperative(n, obj);
      } else if (obj !== null && member === "togglePopover") {
        const force = args[0] === undefined ? undefined : strip(args[0]);
        if (force === undefined || force.kind !== ts.SyntaxKind.TrueKeyword) flagImperative(n, obj);
      } else if (obj !== null && (member === "close" || member === "requestClose") && isDialogElement(obj)) {
        flagImperative(n, obj);
      }
    }
    n.forEachChild(imperativeVisit);
  };
  imperativeVisit(sf);

  return { violations: out, parseError: null, ownerCalls: contains(sf, callsOwner), ladderSites, imperativeHides };
}

/* ── off-cluster debt, routed to its owners (ratchet: shrink only) ─────────── */

/**
 * Violations in files this cluster does not own. Each is reported to the orchestrator with its
 * file:line and must be fixed by that file's owner by calling `returnFocus`. Keyed by the
 * normalised condition or call text so a line shift does not churn it; an entry that stops
 * matching fails the suite until it is removed.
 */
const PENDING_ROUTING: readonly { file: string; kind: Violation["kind"]; text: string }[] = [
  /* Shapes 1-4: none — every off-cluster site routed through the owner (shapes 1-3: merged-tree gate,
     wave 2c; shape 4's three state-driven hides — the queue's Group/Order/Display block, TabPanel and
     Disclosure — engine gate, 2026-09-27). A new entry is debt, never an allowance. */
  /* Shape 6: the dialog stack's two imperative `inert` writes (`inertOutside`'s `visit`, `restack`) release
     focus into the top dialog's panel before they land (engine gate, 2026-09-28). The entries below are the
     members of the DOM-effect class (independent verifier R5-V2-4) that the spelling list could not see —
     removals and content replacements of an element that can hold focus — in files other clusters own.
     Each is fixed by calling the third door on the element (`releaseFocusFrom(<it>, null, <stated
     successors>)`) before the write, a no-op when focus is elsewhere; then its entry is deleted here. */
  { file: "src/fabric3d/Fabric3D.tsx", kind: "imperative-hide-without-release", text: "Fabric3D: canvas.remove()" }, // Q-D: the focusable canvas (tabIndex 0), removed on a failed scene and in the effect's cleanup (two sites, one key)
  { file: "src/fabric3d/scene.ts", kind: "imperative-hide-without-release", text: "createSceneImpl: el.remove()" }, // Q-C: the tier-fade overlay's unmount
  { file: "src/main.tsx", kind: "imperative-hide-without-release", text: "datasetReady: boot.textContent = message" }, // Q-M: the boot line's contents replaced
  { file: "src/core/dataset/refusal.ts", kind: "imperative-hide-without-release", text: "showDatasetRefusal: boot.textContent = text" }, // Q-M: the refusal replaces the boot line's contents (moved here from main.tsx's showRefusal)
  { file: "src/dev/preview.tsx", kind: "imperative-hide-without-release", text: "Preview: slot.replaceChildren(canvas)" }, // unowned dev preview (gate): replaces a focusable canvas
  { file: "src/dev/preview.tsx", kind: "imperative-hide-without-release", text: "Preview: slot.replaceChildren()" }, // unowned dev preview (gate)
  /* Shape 6, read through the STYLESHEETS (independent verifier QH-V1-5, phase 3.5 repair): a data attribute a
     rendering rule keys on. Fabric3D.css hides `.fabric3d-label[data-visible="false"]` (visibility: hidden) and
     SHOWS each chip only while its label carries the matching `data-alarm` / `-cut` / `-stranded` / `-finding` /
     `-disputed` value (display: inline-flex), so each write below can stop an element rendering. The labels sit in
     an aria-hidden layer and hold no tab stop today, which the guard cannot know from the source: the owner (Q-C,
     FabricLabels.tsx) either routes the write through the third door (`releaseFocusFrom(el, null)`, a no-op when
     focus is elsewhere) or makes the label layer unable to hold focus in a way the guard can read; then the entry
     goes. */
  { file: "src/fabric3d/FabricLabels.tsx", kind: "imperative-hide-without-release", text: 'hide: el.dataset.visible = "false"' }, // Q-C
  { file: "src/fabric3d/FabricLabels.tsx", kind: "imperative-hide-without-release", text: "tick: el.dataset.alarm = wantAlarm" }, // Q-C
  { file: "src/fabric3d/FabricLabels.tsx", kind: "imperative-hide-without-release", text: "tick: el.dataset.cut = wantCut" }, // Q-C
  { file: "src/fabric3d/FabricLabels.tsx", kind: "imperative-hide-without-release", text: "tick: el.dataset.stranded = wantStranded" }, // Q-C
  { file: "src/fabric3d/FabricLabels.tsx", kind: "imperative-hide-without-release", text: "tick: el.dataset.finding = wantFinding" }, // Q-C
  { file: "src/fabric3d/FabricLabels.tsx", kind: "imperative-hide-without-release", text: "tick: el.dataset.disputed = wantDisputed" }, // Q-C
];

const key = (v: { file: string; kind: string; text: string }): string => `${v.file}|${v.kind}|${v.text}`;

/* ── the tests ─────────────────────────────────────────────────────────────── */

describe("the focus-return guard's denominator is the runner's own", () => {
  it("derives a non-empty root and extension set from vitest.config.ts", () => {
    expect(INCLUDE.length).toBeGreaterThan(0);
    expect(ROOTS).toContain("src");
    expect([...EXTS].sort()).toEqual([".ts", ".tsx"]);
  });

  it("partitions every .ts/.tsx under the root into test or scanned source, with no third bucket", () => {
    const tests = CANDIDATES.filter(isTest);
    expect(tests.length + SOURCES.length).toBe(CANDIDATES.length);
    /* The two files this guard exists for, and its owner, are in the scanned set. */
    for (const f of ["src/app/Header.tsx", "src/panels/DataGrid.tsx", OWNER]) expect(SOURCES).toContain(f);
    expect(SOURCES).not.toContain("src/app/focus-return.guard.test.ts");
    expect(SOURCES.length).toBeGreaterThan(40);
  });
});

/* THE PROGRAM, BUILT ONCE AND COUNTED; THE SCAN, ONE FILE PER CASE (acceptance F2, W6 gate 2026-09-25).
   "parses every scanned source file" built the program AND analysed every source file in one test:
   ~5 s on a quiet host, 148 s on a saturated clone, where it failed. The program is now built once
   per file (lazily, so a single case run with -t still builds it) and the build is COUNTED, as
   tracked-sources.test.ts counts its own; each scanned file is analysed in a case of its own, once,
   and the ledger and owner-routing checks read those same per-file results. Same denominator
   (SOURCES), same analysis, same verdict. */
let programsBuilt = 0;
let sourcesProgram: ts.Program | null = null;
const program = (): ts.Program => {
  if (sourcesProgram === null) {
    programsBuilt += 1;
    sourcesProgram = makeProgram(SOURCES);
  }
  return sourcesProgram;
};
const analysed = new Map<string, Analysis>();
const analysisOf = (f: string): Analysis => {
  let a = analysed.get(f);
  if (a === undefined) {
    a = analyseFile(program(), f);
    analysed.set(f, a);
  }
  return a;
};

describe("no surface decides focus return on its own (acceptance D3)", () => {
  const pending = new Set(PENDING_ROUTING.map(key));

  it("builds the scanned sources' program (once: every per-file case below shares it)", () => {
    expect(program().getSourceFiles().filter((sf) => !sf.isDeclarationFile).length).toBeGreaterThanOrEqual(SOURCES.length);
  }, 120_000);

  for (const f of SOURCES) {
    it(`${f}: parses (unscanned is not clean), and decides no focus return on its own`, () => {
      const a = analysisOf(f);
      expect(a.parseError, `${f} did not parse`).toBeNull();
      /* No blur(), no un-owned isConnected fallback and no direct focus of a captured origin
         outside focus-return.ts (analyseFile exempts the owner itself). */
      const fresh = a.violations.filter((v) => !pending.has(key(v))).map((v) => `${v.file}:${v.line} ${v.kind}: ${v.text}`);
      expect(fresh).toEqual([]);
    });
  }

  it("every routed off-cluster entry still exists (delete it once its owner fixes it)", () => {
    const found = new Set(PENDING_ROUTING.flatMap((p) => analysisOf(p.file).violations).map(key));
    expect(PENDING_ROUTING.filter((p) => !found.has(key(p))).map(key)).toEqual([]);
  });

  it("routes Header.tsx and DataGrid.tsx through the owner", () => {
    for (const f of ["src/app/Header.tsx", "src/panels/DataGrid.tsx"]) {
      expect(analysisOf(f).ownerCalls, f).toBe(true);
    }
  });

  it("shape 4 found what it guards: the rails' state-driven hides are scanned and route through the third door", () => {
    /* Not vacuous: surfaces.tsx renders `hidden={hidden}` on both rails and on Rail B's panes, and
       would be flagged if RailA/RailB did not call the third door (the planted cases below prove the
       detector fires on exactly that shape). */
    const a = analysisOf("src/app/surfaces.tsx");
    expect(a.ownerCalls).toBe(true);
    expect(a.violations.filter((v) => v.kind === "hidden-without-release")).toEqual([]);
    /* Non-vacuity from the real tree, not from routing debt (verifier D3-R2-2: requiring a pending
       entry made the fix of the last one turn this red): the files above really carry state-driven
       hides that shape 4 inspected and found door-bound. */
    for (const f of ["src/app/surfaces.tsx", "src/ui/primitives.tsx", "src/panels/PriorityQueue.tsx"]) {
      const text = readFileSync(absOf(f), "utf8");
      expect(/\bhidden=\{(?!\s*(?:true|false)\s*\})/.test(text), `${f} carries a state-driven hidden={…}`).toBe(true);
      expect(analysisOf(f).violations.filter((v) => v.kind === "hidden-without-release"), f).toEqual([]);
    }
  });

  it("shape 5 found what it guards: the ladder's readers render from it and declare the layout door", () => {
    /* Non-vacuity from the real tree: App.tsx (the pane switch, the rails' hides, data-drawer) and
       Header.tsx (the More popover / inline toolbar swap) render from the ladder — shape 5 counted
       those sites — and each declares the fourth door keyed on it. */
    for (const f of ["src/app/App.tsx", "src/app/Header.tsx"]) {
      const a = analysisOf(f);
      expect(a.ladderSites, `${f}: no ladder-keyed render site was found, so shape 5 inspected nothing there`).toBeGreaterThan(0);
      expect(a.violations.filter((v) => v.kind === "ladder-render-without-layout-door"), f).toEqual([]);
    }
  });

  it("shape 6 found what it guards: the fabric's off-view pointer hides imperatively and routes through the third door", () => {
    /* Non-vacuity from the real tree: FabricLabels.tsx hides a focused pointer with `el.hidden = true`
       (verifier R5-V2) — shape 6 counted it — and releases it through `releaseFocusFrom` first. */
    const a = analysisOf("src/fabric3d/FabricLabels.tsx");
    expect(a.imperativeHides, "shape 6 inspected no imperative hide in FabricLabels.tsx").toBeGreaterThan(0);
    /* The pointer's hide is door-bound; the file's other shape-6 sites (the label layer's data attributes, read
       through the stylesheet since QH-V1-5) are routed debt, named one by one in PENDING_ROUTING — never absorbed. */
    const shape6 = a.violations.filter((v) => v.kind === "imperative-hide-without-release");
    expect(shape6.filter((v) => v.text.startsWith("hidePointer:")), "the off-view pointer's hide is not released").toEqual([]);
    expect(shape6.filter((v) => !pending.has(key(v))).map((v) => `${v.line} ${v.text}`)).toEqual([]);
    const total = SOURCES.reduce((n, f) => n + analysisOf(f).imperativeHides, 0);
    expect(total, "the imperative hides shape 6 inspected across the scanned tree").toBeGreaterThanOrEqual(3);
  });

  it("shape 6 reads the stylesheets: every .css under the scanned root, and the drawer's stylesheet hide is a rendering rule", () => {
    /* Non-vacuity of the class/attribute half (QH-V1-5): the stylesheets are the runner's root's own, each is
       read, and the one stylesheet hide this guard's header names is among the rendering rules, keyed on its
       attribute: at the drawer rung Rail B is `visibility: hidden` and SHOWN only while `.app[data-drawer="open"]`
       matches (shell.css), so a write that un-matches it hides the rail — a rule that SHOWS, read as one. */
    expect(STYLESHEETS.length, "no stylesheet under the scanned root").toBeGreaterThan(5);
    const rules = RENDERING();
    for (const f of STYLESHEETS) expect(readFileSync(absOf(f), "utf8").length, f).toBeGreaterThan(0);
    expect(rules.length, "no rendering rule read from the stylesheets").toBeGreaterThan(10);
    expect(
      rules.some((r) => r.file === "src/app/shell.css" && r.shows && r.mentions.some((m) => m.kind === "attr" && m.name === "data-drawer" && m.value === "open" && !m.negated)),
      "shell.css's data-drawer hide was not read as a rendering rule",
    ).toBe(true);
  });

  it("built the scanned sources' program at most once for all of the cases above", () => {
    expect(programsBuilt, "the program was built more than once").toBeLessThanOrEqual(1);
  });
});

describe("the guard is live (planted counterexamples, compiled with the real owner)", () => {
  /* Every planted module is compiled into ONE program next to the real `focus-return.ts`, so an
     import of the owner resolves exactly as it does in the application. */
  const PLANTED: Record<string, { src: string; css?: string; expect: Violation["kind"][] }> = {
    d3Regression: {
      src: `export function onEsc(e: { currentTarget: HTMLElement }, back: HTMLElement | null) {
        if (back && back.isConnected) back.focus();
        else e.currentTarget.blur();
      }`,
      expect: ["blur-call", "isConnected-fallback"],
    },
    blurSpellings: {
      src: `declare const el: HTMLElement;
        el.blur(); el?.blur?.(); el["blur"](); HTMLElement.prototype.blur.call(el); (el as HTMLElement).blur(); el!.blur();`,
      expect: ["blur-call", "blur-call", "blur-call", "blur-call", "blur-call", "blur-call"],
    },
    noElseArm: {
      src: `declare const el: HTMLElement;
        if (el.isConnected) el.focus();
        void (el.isConnected ? el.focus() : undefined);
        el.isConnected && el.focus();
        if (!el.isConnected) {} else { el.focus(); }`,
      expect: ["isConnected-fallback", "isConnected-fallback", "isConnected-fallback", "isConnected-fallback"],
    },
    livenessThroughAHelper: {
      src: `declare const el: HTMLElement;
        const live = (x: HTMLElement): boolean => x.isConnected;
        function stillThere(x: HTMLElement): boolean { return live(x); }
        if (stillThere(el)) el.focus();`,
      expect: ["isConnected-fallback"],
    },
    capturedOriginModuleState: {
      /* The Inspector shape: module state captured from activeElement, focused unguarded later. */
      src: `let back: HTMLElement | null = null;
        export function open(): void { const a = document.activeElement; back = a instanceof HTMLElement ? a : null; }
        export function close(): void { back?.focus(); }`,
      expect: ["captured-origin-focus"],
    },
    capturedOriginRef: {
      /* The Dialog / StatusBar shape: a ref's .current captured on open. */
      src: `const returnTo: { current: HTMLElement | null } = { current: null };
        export function open(): void { returnTo.current = document.activeElement as HTMLElement | null; }
        export function close(): void { returnTo.current?.focus(); }`,
      expect: ["captured-origin-focus"],
    },
    capturedOriginRelatedTarget: {
      src: `export function onFocus(e: FocusEvent): void {
          const from = e.relatedTarget;
          const t = from instanceof HTMLElement ? from : null;
          window.setTimeout(() => t?.focus(), 0);
        }`,
      expect: ["captured-origin-focus"],
    },
    ownerCallsAccepted: {
      src: `import { returnFocus, recordReturn } from "./focus-return";
        import { returnFocus as rf } from "./focus-return";
        declare const el: HTMLElement;
        if (el.isConnected) el.focus(); else returnFocus(null, el);
        if (el.isConnected) el.focus(); else rf(null, el);
        export function onFocus(e: FocusEvent): void { const r = recordReturn(e.relatedTarget, el); returnFocus(r, el); }`,
      expect: [],
    },
    lookalikesNotFlagged: {
      /* A local function merely NAMED like the owner is not the owner; strings, comments and event
         names are not calls; an origin used only in a predicate does not taint what the predicate
         selects; and a same-named variable in another function is a different symbol. */
      src: `declare const el: HTMLElement; declare const list: HTMLElement[];
        // el.blur() in a comment
        const s = "el.blur()"; void s;
        el.addEventListener("blur", () => {});
        if (!el.isConnected) { /* nothing to focus */ }
        const next = list.find((x) => x !== document.activeElement); next?.focus();
        export function a(): void { const target = document.activeElement; void target; }
        export function b(): void { const target = document.getElementById("x"); target?.focus(); }`,
      expect: [],
    },
    hiddenByState: {
      /* The Rail B shape before the fix: a DOM element hidden by state, no third-door call. */
      src: `export function Rail({ shown }: { shown: boolean }) {
          return <aside hidden={!shown}><button>inside</button></aside>;
        }
        export function Busy({ busy }: { busy: boolean }) {
          return <div inert={busy}><button>inside</button></div>;
        }`,
      expect: ["hidden-without-release", "hidden-without-release"],
    },
    hiddenWithTheThirdDoor: {
      src: `import { useRef } from "react";
        import { useReleaseFocusOnHide, releaseFocusFrom } from "./focus-return";
        export function Rail({ shown }: { shown: boolean }) {
          const ref = useRef<HTMLElement | null>(null);
          useReleaseFocusOnHide(ref, shown);
          return <aside ref={ref} hidden={!shown}><button>inside</button></aside>;
        }
        export function Panes({ view }: { view: string }) {
          const panes = useRef<Record<string, HTMLDivElement | null>>({});
          for (const v of ["a", "b"]) if (v !== view) releaseFocusFrom(panes.current[v], null);
          return <div>{["a", "b"].map((v) => <div key={v} ref={(el) => { panes.current[v] = el; }} hidden={view !== v} />)}</div>;
        }`,
      expect: [],
    },
    hiddenWithTheDoorOnAnotherElement: {
      /* The door is called in the component, but for a different element than the one hidden: the
         hidden panes are never handed to it (verifier D3-V3). A component-granular check passed this. */
      src: `import { useRef } from "react";
        import { releaseFocusFrom, useReleaseFocusOnHide } from "./focus-return";
        export function Panes({ view }: { view: string }) {
          const box = useRef<HTMLDivElement | null>(null);
          releaseFocusFrom(box.current, null);
          return <div ref={box}>{["a", "b"].map((v) => <div key={v} hidden={view !== v} />)}</div>;
        }
        export function Rail({ shown }: { shown: boolean }) {
          const ref = useRef<HTMLElement | null>(null);
          const other = useRef<HTMLElement | null>(null);
          useReleaseFocusOnHide(ref, shown);
          return <div><section ref={ref} /><aside ref={other} hidden={!shown} /></div>;
        }`,
      expect: ["hidden-without-release", "hidden-without-release"],
    },
    hiddenConstantsAndComponents: {
      /* A constant is not a hide that happens; a component's prop is judged where it reaches the DOM. */
      src: `declare function Rail(p: { hidden: boolean }): null;
        export function A({ x }: { x: boolean }) {
          return <div><div hidden /><div hidden={true} /><div hidden={false} /><Rail hidden={x} /></div>;
        }`,
      expect: [],
    },
    hiddenWithANamesakeDoor: {
      src: `function useReleaseFocusOnHide(_r: unknown, _s: boolean): void {}
        export function Rail({ shown }: { shown: boolean }) {
          useReleaseFocusOnHide(null, shown);
          return <aside hidden={!shown} />;
        }`,
      expect: ["hidden-without-release"],
    },
    ladderRenderWithoutTheDoor: {
      /* The pane-switch shape before the fix: a control mounted only at some rungs, no fourth door. */
      src: `import { useLadder } from "./surfaces";
        export function Frame() {
          const ladder = useLadder();
          const narrow = ladder.singleColumn || ladder.stacked;
          if (ladder.drawer) return <aside />;
          return <div>{narrow ? <button>Queue</button> : null}{ladder.stacked && <button>Show</button>}</div>;
        }`,
      expect: ["ladder-render-without-layout-door", "ladder-render-without-layout-door", "ladder-render-without-layout-door"],
    },
    rungIndexWithoutTheDoor: {
      /* Any hook the ladder's owner exports counts, not only useLadder by name. */
      src: `import { useRungIndex } from "./surfaces";
        export function Frame() {
          const rung = useRungIndex();
          return <div data-rung={rung} />;
        }`,
      expect: ["ladder-render-without-layout-door"],
    },
    ladderThroughALocalHook: {
      /* The Header shape before the fix: the ladder read through a hook of the same file. */
      src: `import { useLadder } from "./surfaces";
        function useCompact(): boolean { const l = useLadder(); return l.stacked || l.singleColumn; }
        export function Bar() {
          const compact = useCompact();
          return compact ? <button>More</button> : <nav><button>Findings</button></nav>;
        }`,
      expect: ["ladder-render-without-layout-door"],
    },
    ladderWithTheDoor: {
      src: `import { useLadder } from "./surfaces";
        import { useReleaseFocusOnLayoutChange } from "./focus-return";
        function useCompact(): boolean { const l = useLadder(); return l.stacked || l.singleColumn; }
        export function Bar() {
          const compact = useCompact();
          useReleaseFocusOnLayoutChange(compact);
          return <div data-compact={compact || undefined}>{compact ? <button>More</button> : <nav>{["a"].map((k) => <button key={k}>{k}</button>)}</nav>}</div>;
        }
        export function Frame() {
          const ladder = useLadder();
          const rung = ladder.stacked ? "stacked" : "wide";
          useReleaseFocusOnLayoutChange(\`\${rung}|x\`);
          return ladder.drawer ? <aside /> : null;
        }`,
      expect: [],
    },
    ladderDoorKeyedOnSomethingElse: {
      src: `import { useState } from "react";
        import { useLadder } from "./surfaces";
        import { useReleaseFocusOnLayoutChange } from "./focus-return";
        export function Frame() {
          const ladder = useLadder();
          const [open] = useState(false);
          useReleaseFocusOnLayoutChange(open);
          return ladder.drawer ? <aside /> : null;
        }`,
      expect: ["ladder-render-without-layout-door"],
    },
    ladderWithANamesakeDoor: {
      src: `import { useLadder } from "./surfaces";
        function useReleaseFocusOnLayoutChange(_k: unknown): void {}
        export function Frame() {
          const ladder = useLadder();
          useReleaseFocusOnLayoutChange(ladder.drawer);
          return ladder.drawer ? <aside /> : null;
        }`,
      expect: ["ladder-render-without-layout-door"],
    },
    ladderReadButNotRendered: {
      /* Reading the ladder for a command (App's evidence.toggle) renders nothing from it. */
      src: `import { useEffect } from "react";
        import { useLadder } from "./surfaces";
        export function Frame() {
          const ladder = useLadder();
          useEffect(() => { if (ladder.drawer) document.title = "drawer"; }, [ladder.drawer]);
          return <div />;
        }`,
      expect: [],
    },
    imperativeHideWithoutRelease: {
      /* The FabricLabels pointer shape before the fix (verifier R5-V2), in every spelling that stops
         an element being rendered from script: the property, the attribute, and the two styles. */
      src: `declare const el: HTMLElement; declare const busy: boolean; declare const v: string;
        el.hidden = true;
        el.inert = busy;
        el["hidden"] = busy;
        el.setAttribute("hidden", "");
        el.toggleAttribute("inert");
        el.style.display = "none";
        el.style.visibility = v;
        el.style.setProperty("display", "none");`,
      expect: [
        "imperative-hide-without-release",
        "imperative-hide-without-release",
        "imperative-hide-without-release",
        "imperative-hide-without-release",
        "imperative-hide-without-release",
        "imperative-hide-without-release",
        "imperative-hide-without-release",
        "imperative-hide-without-release",
      ],
    },
    imperativeHideByEffect: {
      /* Independent verifier R5-V2-4: shape 6 matched a list of SPELLINGS, and ten planted hides went
         through seven of them unflagged. The class is the DOM EFFECT — a write that leaves an element, or
         what is inside it, unrendered or detached — however it is spelled: the whole style (cssText, the
         style attribute, Object.assign), content-visibility, the namespaced attribute, the popover and
         dialog APIs, and removal of an element or of its contents. */
      src: `declare const el: HTMLElement; declare const pop: HTMLElement; declare const dlg: HTMLDialogElement;
        declare const s: string; declare const parent: HTMLElement; declare const child: HTMLElement;
        el.style.cssText = "display: none";
        el.setAttribute("style", "display: none");
        Object.assign(el.style, { display: "none" });
        el.remove();
        pop.hidePopover();
        el.setAttributeNS(null, "hidden", "");
        el.style.contentVisibility = "hidden";
        el.style.cssText = s;
        pop.togglePopover();
        dlg.close();
        parent.removeChild(child);
        parent.replaceChildren();
        el.replaceWith(document.createElement("i"));
        el.innerHTML = "";
        el.textContent = s;
        parent.replaceChild(document.createElement("i"), child);
        el.style.setProperty("content-visibility", "hidden");
        export function t(): void { const b = document.createElement("button"); document.body.append(b); b.focus(); b.remove(); }`,
      expect: Array.from({ length: 18 }, () => "imperative-hide-without-release" as const),
    },
    imperativeEffectsThatHideNothing: {
      /* Not the class: a style write that sets no hiding value, a class toggle no stylesheet keys a rendering
         rule on (this case declares no stylesheet; see imperativeHideByStylesheet), a database's close, a text
         node's text, a removed property no rule renders by, an explicit show — and a TEMPORARY: an element this
         very function created and never focused cannot be holding the reader's focus (the Inspector's download
         anchor). (`el.style.removeProperty("display")` stood here until phase 3.5's repair: removing an inline
         `display` can un-override a stylesheet's `none`, so it is in the class — imperativeHideByStylesheet.) */
      src: `declare const el: HTMLElement; declare const db: IDBDatabase; declare const t: Text;
        el.style.cssText = "position:absolute;opacity:1";
        el.setAttribute("style", "color: red");
        Object.assign(el.style, { opacity: "0.5" });
        el.classList.remove("shown");
        db.close();
        t.textContent = "x";
        el.style.removeProperty("color");
        el.togglePopover(true);
        export function download(): void { const a = document.createElement("a"); a.href = "x"; document.body.append(a); a.click(); a.remove(); }`,
      expect: [],
    },
    imperativeHideByStylesheet: {
      /* Independent verifier QH-V1-5: 14 of 20 planted hides flagged; not a class added (`classList.add`) or
         replaced (`className =`), a `dataset` write, or a style reached through an alias (`const s = el.style`).
         A class or attribute hides through the STYLESHEET, so the stylesheet is read (renderingRules): a rule
         that decides rendering and keys on what the write changes. Here: a class a rule hides, the whole class
         list replaced, a data attribute set to the value a rule hides, a value not knowable, a class a
         `:not()` rule hides by its ABSENCE, a value that un-matches a rule that SHOWS a descendant, that
         attribute removed, the class attribute removed, the style alias, a custom property a rendering rule
         reads, an inline rendering property removed (it may have overridden a sheet's `none`), the typed OM,
         a <details> closed, a class not knowable, a style object of unknown origin (fails closed: no door can
         name its element) and a stylesheet rewritten (any element). */
      css: `.is-hidden { display: none; }
        .card[data-open="false"] { visibility: hidden; }
        .panel[data-state="on"] .panel__body { display: block; }
        .x:not(.shown) { display: none; }
        .var-host { display: var(--vis); }
        .deco::after { display: none; }`,
      src: `declare const el: HTMLElement; declare const v: string; declare const d: HTMLDetailsElement; declare const sheet: CSSStyleSheet;
        el.classList.add("is-hidden");
        el.className = "card";
        el.dataset.open = "false";
        el.setAttribute("data-open", v);
        el.classList.remove("shown");
        el.dataset.state = "off";
        delete el.dataset.state;
        el.removeAttribute("class");
        const s = el.style; s.display = "none";
        el.style.setProperty("--vis", "none");
        el.style.removeProperty("display");
        el.attributeStyleMap.set("display", "none");
        d.open = false;
        el.classList.toggle(v);
        export function f(st: CSSStyleDeclaration): void { st.display = "none"; }
        sheet.insertRule(".a { display: none }");
        export function mk(): HTMLElement { const c = document.createElement("canvas"); document.body.append(c); c.focus(); c.className = "is-hidden"; return c; }`,
      expect: Array.from({ length: 17 }, () => "imperative-hide-without-release" as const),
    },
    stylesheetWritesThatHideNothing: {
      /* The same stylesheet, and writes that cannot stop anything rendering through it: a value its one exact
         hide cannot match, a class and a data attribute no rendering rule keys on, the value its SHOWING rule
         matches, a custom property no rendering rule reads, an ARIA label, a colour through the style alias, a
         class only a pseudo-element's rule keys on — and a class hide released through the third door first. */
      css: `.is-hidden { display: none; }
        .card[data-open="false"] { visibility: hidden; }
        .panel[data-state="on"] .panel__body { display: block; }
        .var-host { display: var(--vis); }
        .deco::after { display: none; }
        .shown-thing { display: block; }`,
      src: `import { releaseFocusFrom } from "./focus-return";
        declare const el: HTMLElement;
        export function mk(): HTMLElement { const c = document.createElement("canvas"); document.body.append(c); c.focus(); c.className = "shown-thing"; return c; }
        el.dataset.open = "true";
        el.classList.add("unrelated");
        el.dataset.state = "on";
        el.dataset.unrelated = "x";
        el.style.setProperty("--pointer-deg", "12deg");
        el.setAttribute("aria-label", "x");
        const t = el.style; t.color = "red";
        el.classList.add("deco");
        export function hide(box: HTMLElement): void { releaseFocusFrom(box, null); box.classList.add("is-hidden"); }`,
      expect: [],
    },
    imperativeDoorOnTheRightElement: {
      /* The door is bound to the element's own access path, or an ANCESTOR of it (releasing a container
         releases everything inside it) — never to anything merely rooted at the same variable: a door
         on a DESCENDANT does not release the element (verifier R5-V2-4: el.parentElement and
         el.firstElementChild both passed as "el"). */
      src: `import { releaseFocusFrom } from "./focus-return";
        export function f(el: HTMLElement): void { releaseFocusFrom(el.firstElementChild, null); el.hidden = true; }
        export function g(el: HTMLElement): void { releaseFocusFrom(el.parentElement, null); el.hidden = true; }
        export function h(el: HTMLElement): void { releaseFocusFrom(el, null); el.remove(); }
        export function k(box: { current: HTMLElement | null }): void { releaseFocusFrom(box.current, null); box.current?.setAttribute("inert", ""); }`,
      expect: ["imperative-hide-without-release"],
    },
    imperativeHideWithTheThirdDoor: {
      src: `import { releaseFocusFrom } from "./focus-return";
        export function hidePointer(el: HTMLElement): void {
          releaseFocusFrom(el, null, []);
          el.hidden = true;
        }
        export function underneath(nodes: HTMLElement[]): void {
          for (const n of nodes) { releaseFocusFrom(n, null); n.setAttribute("inert", ""); }
        }`,
      expect: [],
    },
    imperativeShowsAreNotHides: {
      /* Showing, un-hiding and a style that does not hide are not the class; aria-hidden moves no focus. */
      src: `declare const el: HTMLElement;
        el.hidden = false;
        el.inert = false;
        el.toggleAttribute("hidden", false);
        el.removeAttribute("hidden");
        el.setAttribute("aria-hidden", "true");
        el.style.display = "block";
        el.style.visibility = "visible";
        el.style.setProperty("--pointer-deg", "12deg");`,
      expect: [],
    },
    imperativeHideDoorOnAnotherElement: {
      /* The door released some OTHER element: this hide is still unreleased (element-bound, as shape 4). */
      src: `import { releaseFocusFrom } from "./focus-return";
        export function f(a: HTMLElement, b: HTMLElement): void {
          releaseFocusFrom(a, null);
          b.hidden = true;
        }`,
      expect: ["imperative-hide-without-release"],
    },
    localNamesakeIsNotTheOwner: {
      src: `declare const el: HTMLElement;
        function returnFocus(_a: unknown, _b: unknown): void {}
        if (el.isConnected) el.focus(); else returnFocus(null, el);`,
      expect: ["isConnected-fallback"],
    },
  };
  const rel = (name: string): string => `src/app/__planted_${name}.tsx`;
  let program: ts.Program | null = null;
  const planted = (name: string): Analysis => {
    program ??= makeProgram([OWNER], new Map(Object.entries(PLANTED).map(([n, p]) => [rel(n), p.src])));
    /* A planted case is judged against ITS OWN stylesheet (none unless it declares one), never the app's. */
    return analyseFile(program, rel(name), renderingRules(`__planted_${name}.css`, PLANTED[name]!.css ?? ""));
  };

  for (const [name, p] of Object.entries(PLANTED)) {
    it(`${name}: flags ${p.expect.length === 0 ? "nothing" : p.expect.join(", ")}`, () => {
      const r = planted(name);
      expect(r.parseError).toBeNull();
      expect(r.violations.map((v) => v.kind).sort()).toEqual([...p.expect].sort());
    }, 60_000);
  }

  it("the owner itself is exempt (it is the one place allowed to decide)", () => {
    const r = analyseFile(makeProgram([OWNER]), OWNER);
    expect(r.parseError).toBeNull();
    expect(r.violations).toEqual([]);
  }, 60_000);
});

/* ── the third door's successor does not depend on history (independent verifier R5-V2-5) ────────────
 * MEASURED (release build, probe-stale.mjs): at 1440 px, focus on the evidence rail's first citation, a
 * resize to 1152 hides the rail — and focus went to MAIN "Fabric" on a fresh load, but to the queue's
 * "Filter findings" after an earlier 1440 -> 1152 -> 1440 round trip with the filter focused. The rail's
 * third door recorded whatever held focus at EVERY hidden -> shown transition, a resize back included,
 * and a later hide returned there: a landing chosen by history, not by the layout. The record means "the
 * control that OPENED this container" (the drawer's opener), so it is taken only when a reader's action
 * shows the container; a show that is part of a commit changing a DECLARED layout (the fourth door's
 * key) records nothing, and its hide goes to the stated successors — the same place a fresh load goes.
 * These cases drive the owner's hooks directly, as the rails use them. */
describe("the third door's successor does not depend on history (R5-V2-5)", () => {
  function Rail({ hidden, closed }: { hidden: boolean; closed: boolean }): ReactElement {
    const ref = useRef<HTMLElement | null>(null);
    useReleaseFocusOnHide(ref, !hidden && !closed, () => [document.getElementById("stated")]);
    return createElement("aside", { ref, hidden, "aria-label": "Evidence" }, createElement("button", { id: "cite", type: "button" }, "Cite"));
  }
  function Frame({ layout, closed }: { layout: "wide" | "narrow"; closed: boolean }): ReactElement {
    /* The frame declares its layout to the owner, as App.tsx does with the rung. */
    useReleaseFocusOnLayoutChange(layout);
    return createElement(
      "div",
      null,
      createElement("button", { id: "filter", type: "button" }, "Filter findings"),
      createElement("button", { id: "other", type: "button" }, "Other"),
      createElement("button", { id: "stated", type: "button" }, "Stated successor"),
      createElement(Rail, { hidden: layout === "narrow", closed }),
    );
  }
  let root: Root | null = null;
  let host: HTMLElement | null = null;
  const render = (layout: "wide" | "narrow", closed = false): void => {
    if (host === null) {
      host = document.createElement("div");
      document.body.appendChild(host);
      root = createRoot(host);
    }
    act(() => {
      root!.render(createElement(Frame, { layout, closed }));
    });
  };
  const focusOn = (id: string): void => {
    act(() => {
      document.getElementById(id)!.focus();
    });
  };
  const at = (): string => (document.activeElement as HTMLElement | null)?.id || document.activeElement?.tagName || "null";
  afterEach(() => {
    if (root !== null) act(() => root!.unmount());
    host?.remove();
    root = null;
    host = null;
  });

  it("a layout hide lands where a fresh load lands, whatever showed the rail before (the verifier's round trip)", async () => {
    /* Fresh: the rail was shown from the first render; focus inside; the layout hides it. */
    render("wide");
    focusOn("cite");
    render("narrow");
    await actAsync(async () => {});
    const fresh = at();
    act(() => root!.unmount());
    host!.remove();
    root = null;
    host = null;
    /* History: the rail was shown by a LAYOUT change while "Filter findings" held focus; the reader then
       moved on and into the rail; the layout hides it again. */
    render("narrow");
    focusOn("filter");
    render("wide");
    await actAsync(async () => {});
    focusOn("other");
    focusOn("cite");
    render("narrow");
    await actAsync(async () => {});
    expect(fresh, "precondition: a fresh load hands focus to the stated successor").toBe("stated");
    expect(at(), "the landing after a round trip is the same as a fresh load's, not the control focused when a resize showed the rail").toBe(fresh);
  });

  it("a rail a reader's action showed still returns to the control that showed it (the drawer's opener)", async () => {
    render("wide", true);
    focusOn("filter");
    render("wide", false); /* shown by a command, no layout change */
    await actAsync(async () => {});
    focusOn("cite");
    render("wide", true);
    await actAsync(async () => {});
    expect(at(), "the opener recorded when the reader's action showed the rail").toBe("filter");
  });
});
