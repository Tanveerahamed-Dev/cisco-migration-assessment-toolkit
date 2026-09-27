/**
 * focus-return.guard.test.ts — the STRUCTURAL guard for acceptance D3: nothing but
 * `src/app/focus-return.ts` decides where focus goes when a surface lets go of it.
 *
 * WHY A COMPILER AND NOT A GREP. The D3 regression was two lines: an `isConnected` check and an
 * else-arm that called `blur()`. Fixing the two sites the acceptance report named would leave the
 * class open — the next surface written with the same lines reintroduces it silently — and a grep
 * for `.blur()` both misses `el?.blur?.()` / `el["blur"]()` / `blur.call(el)` and cries wolf on
 * prose and strings. So every source file is compiled into ONE TypeScript program (the project's own
 * tsconfig, imports resolved, as `src/core/band-read.guard.test.ts` does) and four shapes are
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
import ts from "typescript";
import { describe, expect, it } from "vitest";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OWNER = "src/app/focus-return.ts";

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
  kind: "blur-call" | "isConnected-fallback" | "captured-origin-focus" | "hidden-without-release";
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
}

export function analyseFile(program: ts.Program, rel: string): Analysis {
  const sf = program.getSourceFile(absOf(rel));
  if (sf === undefined) return { violations: [], parseError: "not in the program", ownerCalls: false };
  const diags = program.getSyntacticDiagnostics(sf);
  if (diags.length > 0) {
    const first = diags[0]!;
    const { line } = sf.getLineAndCharacterOfPosition(first.start ?? 0);
    return { violations: [], parseError: `line ${line + 1}: ${ts.flattenDiagnosticMessageText(first.messageText, " ")}`, ownerCalls: false };
  }
  if (rel === OWNER) return { violations: [], parseError: null, ownerCalls: false };
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
  return { violations: out, parseError: null, ownerCalls: contains(sf, callsOwner) };
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

  it("built the scanned sources' program at most once for all of the cases above", () => {
    expect(programsBuilt, "the program was built more than once").toBeLessThanOrEqual(1);
  });
});

describe("the guard is live (planted counterexamples, compiled with the real owner)", () => {
  /* Every planted module is compiled into ONE program next to the real `focus-return.ts`, so an
     import of the owner resolves exactly as it does in the application. */
  const PLANTED: Record<string, { src: string; expect: Violation["kind"][] }> = {
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
    return analyseFile(program, rel(name));
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
