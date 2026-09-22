/**
 * focus-return.guard.test.ts — the STRUCTURAL guard for acceptance D3: nothing but
 * `src/app/focus-return.ts` decides where focus goes when a surface lets go of it.
 *
 * WHY A PARSER AND NOT A GREP. The D3 regression was two lines: an `isConnected` check and an
 * else-arm that called `blur()`. Fixing the two sites the acceptance report named would leave the
 * class open — the next surface written with the same two lines reintroduces it silently, and a
 * grep for `.blur()` both misses `el?.blur?.()` / `el["blur"]()` / `blur.call(el)` and cries wolf
 * on prose and strings. So every source file is parsed with the TypeScript compiler, exactly as
 * `src/core/claim-lint.test.ts` does, and two shapes are rejected:
 *
 *   1. ANY call of a `blur` member outside the owner. `blur()` never moves focus; it removes it, and
 *      the browser parks it on <body>.
 *   2. ANY focus branch keyed on `isConnected` — an `if`, a ternary or a `&&` whose condition reads
 *      `.isConnected` and whose taken arm calls `.focus()` — whose other arm does not call the
 *      owner. A missing else-arm counts: "if it is still there focus it, otherwise do nothing" is
 *      the same drop to <body> by omission.
 *
 * THE DENOMINATOR IS THE TEST RUNNER'S OWN. The files scanned are derived from `vitest.config.ts`'s
 * `include` globs rather than a directory written here: every `.ts`/`.tsx` below the globs' root
 * that the runner does NOT treat as a test is source, and is scanned. A partition check asserts
 * that every file under that root is either a test or scanned, so the set cannot quietly narrow,
 * and a file that fails to parse is reported as UNSCANNED, never as clean.
 *
 * OFF-CLUSTER DEBT is listed in PENDING_ROUTING, keyed by file and the normalised source of the
 * condition (not by line, which drifts). It is a ratchet, not an allowance: an entry that no longer
 * matches fails the suite until it is deleted, and a new violation anywhere is never absorbed by it.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, matchesGlob, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OWNER = "src/app/focus-return.ts";

const toPosix = (p: string): string => p.split(sep).join("/");

/* ── the denominator, from the runner's config ─────────────────────────────── */

/**
 * The  globs, read from vitest.config.ts by PARSING it (importing it would pull the
 * whole Vite config, plugins and all, into the type-checked program). Every string literal of the
 * first  array-literal property is a glob; a config this cannot read yields an empty list,
 * which the first test below rejects rather than scanning nothing and passing.
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
/** The extension a glob ends in: `src/**\/*.test.tsx` → `.tsx`. */
const globExt = (g: string): string => extname(g);

const ROOTS = [...new Set(INCLUDE.map(globRoot))];
const EXTS = new Set(INCLUDE.map(globExt));
const isTest = (rel: string): boolean => INCLUDE.some((g) => matchesGlob(rel, g));

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(toPosix(relative(ROOT, p)));
  }
  return out;
}

const ALL = ROOTS.flatMap((r) => walk(join(ROOT, r)));
const CANDIDATES = ALL.filter((f) => EXTS.has(extname(f)) && !f.endsWith(".d.ts"));
const SOURCES = CANDIDATES.filter((f) => !isTest(f));

/* ── the analysis ──────────────────────────────────────────────────────────── */

export interface Violation {
  file: string;
  line: number;
  kind: "blur-call" | "isConnected-fallback";
  /** Whitespace-normalised source of the offending call or condition. */
  text: string;
}

const norm = (s: string): string => s.replace(/\s+/g, " ").trim();

/** Names this module exports, read from the owner's own source so the list cannot drift. */
function ownerExports(): Set<string> {
  const src = readFileSync(join(ROOT, OWNER), "utf8");
  const sf = ts.createSourceFile(OWNER, src, ts.ScriptTarget.ES2023, true, ts.ScriptKind.TS);
  const names = new Set<string>();
  sf.forEachChild((n) => {
    const exported = ts.canHaveModifiers(n) && ts.getModifiers(n)?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
    if (!exported) return;
    if (ts.isFunctionDeclaration(n) && n.name) names.add(n.name.text);
    if (ts.isVariableStatement(n)) for (const d of n.declarationList.declarations) if (ts.isIdentifier(d.name)) names.add(d.name.text);
  });
  return names;
}
const OWNER_NAMES = ownerExports();

/** The member name a call targets: `a.blur()`, `a?.blur?.()`, `a["blur"]()`, `a.blur.call(x)`. */
function calledMember(call: ts.CallExpression): string | null {
  let callee: ts.Expression = call.expression;
  while (ts.isParenthesizedExpression(callee) || ts.isNonNullExpression(callee)) callee = callee.expression;
  const nameOf = (e: ts.Expression): string | null => {
    if (ts.isPropertyAccessExpression(e)) return e.name.text;
    if (ts.isElementAccessExpression(e) && ts.isStringLiteralLike(e.argumentExpression)) return e.argumentExpression.text;
    return null;
  };
  const direct = nameOf(callee);
  if ((direct === "call" || direct === "apply") && (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee))) {
    return nameOf(callee.expression) ?? direct;
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
const callsOwner = (n: ts.Node): boolean =>
  ts.isCallExpression(n) &&
  ((ts.isIdentifier(n.expression) && OWNER_NAMES.has(n.expression.text)) ||
    (ts.isPropertyAccessExpression(n.expression) && OWNER_NAMES.has(n.expression.name.text)));

export function analyse(source: string, file: string): { violations: Violation[]; parseError: string | null } {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.ES2023, true, kind);
  const diags = (sf as unknown as { parseDiagnostics?: readonly ts.Diagnostic[] }).parseDiagnostics;
  if (diags && diags.length > 0) {
    const first = diags[0]!;
    const { line } = sf.getLineAndCharacterOfPosition(first.start ?? 0);
    return { violations: [], parseError: `line ${line + 1}: ${ts.flattenDiagnosticMessageText(first.messageText, " ")}` };
  }
  const isOwner = file === OWNER;
  const out: Violation[] = [];
  const lineOf = (n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
  const flagBranch = (cond: ts.Expression, taken: ts.Node | undefined, other: ts.Node | undefined, at: ts.Node): void => {
    if (!contains(cond, readsIsConnected)) return;
    /* Either polarity: `if (el.isConnected) el.focus(); else …` and
       `if (!el.isConnected) …; else el.focus()` are the same decision. */
    const takenFocuses = contains(taken, callsFocus);
    if (!takenFocuses && !contains(other, callsFocus)) return;
    /* The fallback arm is the one that does NOT focus; it must hand the decision to the owner. */
    const fallbackArm = takenFocuses ? other : taken;
    if (contains(fallbackArm, callsOwner)) return;
    out.push({ file, line: lineOf(at), kind: "isConnected-fallback", text: norm(cond.getText(sf)) });
  };
  const visit = (n: ts.Node): void => {
    if (!isOwner && ts.isCallExpression(n) && calledMember(n) === "blur") {
      out.push({ file, line: lineOf(n), kind: "blur-call", text: norm(n.getText(sf)) });
    }
    if (!isOwner) {
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
        /* `el.isConnected && el.focus()` used as a statement: a focus branch with no other arm. */
        flagBranch(n.left, n.right, undefined, n);
      }
    }
    n.forEachChild(visit);
  };
  visit(sf);
  return { violations: out, parseError: null };
}

/* ── off-cluster debt, routed to its owners (ratchet: shrink only) ─────────── */

/**
 * Violations in files this cluster does not own. Each is reported to the orchestrator with its
 * file:line and must be fixed by that file's owner by calling `returnFocus`. Keyed by the
 * normalised condition text so a line shift does not churn it; an entry that stops matching fails
 * the suite until it is removed.
 */
const PENDING_ROUTING: readonly { file: string; kind: Violation["kind"]; text: string }[] = [
  /* The palette's retry-landing loop: focuses the landing when connected, with no fallback arm. */
  { file: "src/app/CommandPalette.tsx", kind: "isConnected-fallback", text: "el && el.isConnected" },
  /* The palette's close: returns to the invoker, else its own `landFocus` — a second owner. */
  { file: "src/app/CommandPalette.tsx", kind: "isConnected-fallback", text: "back && back !== document.body && back.isConnected" },
  /* The help sheet's deferred re-focus: nothing happens when the invoker has unmounted. */
  { file: "src/app/keyboard.ts", kind: "isConnected-fallback", text: "target.isConnected && document.activeElement !== target" },
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

describe("no surface decides focus return on its own (acceptance D3)", () => {
  const results = SOURCES.map((f) => ({ f, ...analyse(readFileSync(join(ROOT, f), "utf8"), f) }));

  it("parses every scanned source file (unscanned is not clean)", () => {
    expect(results.filter((r) => r.parseError !== null).map((r) => `${r.f}: ${r.parseError}`)).toEqual([]);
  });

  it("finds no blur() call and no un-owned isConnected focus fallback outside focus-return.ts", () => {
    const pending = new Set(PENDING_ROUTING.map(key));
    const found = results.flatMap((r) => r.violations);
    const fresh = found.filter((v) => !pending.has(key(v))).map((v) => `${v.file}:${v.line} ${v.kind}: ${v.text}`);
    expect(fresh).toEqual([]);
  });

  it("every routed off-cluster entry still exists (delete it once its owner fixes it)", () => {
    const found = new Set(results.flatMap((r) => r.violations).map(key));
    expect(PENDING_ROUTING.filter((p) => !found.has(key(p))).map(key)).toEqual([]);
  });

  it("routes Header.tsx and DataGrid.tsx through the owner", () => {
    for (const f of ["src/app/Header.tsx", "src/panels/DataGrid.tsx"]) {
      const src = readFileSync(join(ROOT, f), "utf8");
      const sf = ts.createSourceFile(f, src, ts.ScriptTarget.ES2023, true, ts.ScriptKind.TSX);
      expect(contains(sf, callsOwner)).toBe(true);
    }
  });
});

describe("the guard is live (planted counterexamples)", () => {
  const planted = (src: string, file = "src/app/Planted.tsx"): Violation[] => {
    const r = analyse(src, file);
    expect(r.parseError).toBeNull();
    return r.violations;
  };

  it("flags the exact shape of the D3 regression", () => {
    const v = planted(`function onEsc(e: { currentTarget: HTMLElement }, back: HTMLElement | null) {
      if (back && back.isConnected) back.focus();
      else e.currentTarget.blur();
    }`);
    expect(v.map((x) => x.kind).sort()).toEqual(["blur-call", "isConnected-fallback"]);
  });

  it("flags blur in every call spelling", () => {
    for (const call of ["el.blur()", "el?.blur?.()", 'el["blur"]()', "HTMLElement.prototype.blur.call(el)", "(el as HTMLElement).blur()", "el!.blur()"]) {
      expect(planted(`declare const el: HTMLElement; ${call};`).map((x) => x.kind), call).toEqual(["blur-call"]);
    }
  });

  it("flags an isConnected focus branch with no else-arm, in if, ternary and && form", () => {
    for (const s of [
      "if (el.isConnected) el.focus();",
      "el.isConnected ? el.focus() : undefined;",
      "el.isConnected && el.focus();",
      "if (!el.isConnected) {} else { el.focus(); }",
    ]) {
      expect(planted(`declare const el: HTMLElement; ${s}`).map((x) => x.kind), s).toEqual(["isConnected-fallback"]);
    }
  });

  it("accepts a branch whose fallback arm calls the owner, and the owner itself", () => {
    expect(
      planted(`import { returnFocus } from "./focus-return";
        declare const el: HTMLElement; if (el.isConnected) el.focus(); else returnFocus(null, el);`),
    ).toEqual([]);
    expect(planted(`declare const el: HTMLElement; el.blur();`, OWNER)).toEqual([]);
  });

  it("does not cry wolf on strings, comments, event names or unrelated isConnected guards", () => {
    expect(
      planted(`declare const el: HTMLElement;
        // el.blur() in a comment
        const s = "el.blur()";
        el.addEventListener("blur", () => {});
        if (!el.isConnected) { /* nothing to focus */ }`),
    ).toEqual([]);
  });
});
