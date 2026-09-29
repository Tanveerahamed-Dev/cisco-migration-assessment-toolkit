// @vitest-environment node
/**
 * golden-preconditions.test.ts — a test skipped by name on another dataset must RUN on the reference sample.
 *
 * Phase 3.5 turned tests whose feature a dataset may lack into named skips: `it.runIf(PRECONDITION)(title, …)`. That
 * is honest only while the precondition is known to hold on the reference sample; otherwise a sample change that made
 * it false silently turns the test into a skip on the one dataset every gate runs, and the "passed" count still reads
 * green (QC-R1-4: blast.test.ts's own-component property test hung on `REACHES`, which no golden block asserted).
 *
 * The class, read from the syntax tree of every test file under src/ that has a golden tier: each identifier a
 * data-dependent `runIf`/`skipIf` condition reads must be read again inside an `expect(…)` inside a `describeGolden`
 * block of the same file — so the golden tier states the precondition and a regression turns it red instead of
 * turning the test into a skip. A condition that reads only the environment (`process.platform`, `process.env`) is
 * not a data precondition and is exempt. An identifier declared inside a `describe` callback cannot be read from the
 * golden block, so the rule forces the precondition to be hoisted where the golden tier can state it.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function testFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory()
      ? /^(_|node_modules$|data$)/.test(e.name)
        ? []
        : testFiles(join(dir, e.name))
      : /\.test\.tsx?$/.test(e.name)
        ? [join(dir, e.name)]
        : [],
  );
}

/** Identifiers an expression reads, excluding property names and `undefined`. */
function readsOf(e: ts.Node): Set<string> {
  const out = new Set<string>();
  const walk = (n: ts.Node): void => {
    if (ts.isIdentifier(n)) {
      const p = n.parent;
      const isPropName = p !== undefined && ts.isPropertyAccessExpression(p) && p.name === n;
      if (!isPropName && n.text !== "undefined") out.add(n.text);
    }
    ts.forEachChild(n, walk);
  };
  walk(e);
  return out;
}

const ENVIRONMENT = new Set(["process"]);

/** Every data precondition a runIf/skipIf reads that no expect() inside a describeGolden block reads again. */
function unstatedPreconditions(fileName: string, text: string): string[] {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const conditions: { line: number; reads: Set<string> }[] = [];
  const goldenExpectReads = new Set<string>();
  let hasGolden = false;
  const collectExpects = (n: ts.Node): void => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "expect") {
      for (const a of n.arguments) for (const r of readsOf(a)) goldenExpectReads.add(r);
    }
    ts.forEachChild(n, collectExpects);
  };
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n)) {
      const callee = n.expression;
      if (ts.isPropertyAccessExpression(callee) && (callee.name.text === "runIf" || callee.name.text === "skipIf") && n.arguments.length === 1) {
        conditions.push({ line: sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1, reads: readsOf(n.arguments[0]!) });
      }
      if (ts.isIdentifier(callee) && callee.text === "describeGolden") {
        hasGolden = true;
        for (const a of n.arguments.slice(1)) collectExpects(a);
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  if (!hasGolden) return [];
  /* A condition may call a local helper (`has("…")` over a HAS table): the helper stands for what its body reads,
     less its own parameters and locals, so stating the table it reads states the helper. */
  const helpers = new Map<string, Set<string>>();
  const helperOf = (name: string, fn: ts.FunctionLikeDeclaration): void => {
    const own = new Set<string>();
    const declared = (b: ts.Node): void => {
      if ((ts.isParameter(b) || ts.isVariableDeclaration(b) || ts.isBindingElement(b)) && ts.isIdentifier(b.name)) own.add(b.name.text);
      ts.forEachChild(b, declared);
    };
    declared(fn);
    helpers.set(name, new Set([...(fn.body === undefined ? [] : readsOf(fn.body))].filter((x) => !own.has(x))));
  };
  /* A loop variable (`for (const [t, pick] of CASES)`) stands for the collection it walks. */
  const loopBound = new Map<string, Set<string>>();
  const bindNames = (b: ts.BindingName, reads: Set<string>): void => {
    if (ts.isIdentifier(b)) loopBound.set(b.text, reads);
    else for (const e of b.elements) if (!ts.isOmittedExpression(e)) bindNames(e.name, reads);
  };
  const findHelpers = (n: ts.Node): void => {
    if (ts.isForOfStatement(n) && ts.isVariableDeclarationList(n.initializer))
      for (const d of n.initializer.declarations) bindNames(d.name, readsOf(n.expression));
    if (ts.isFunctionDeclaration(n) && n.name !== undefined) helperOf(n.name.text, n);
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer !== undefined && (ts.isArrowFunction(n.initializer) || ts.isFunctionExpression(n.initializer)))
      helperOf(n.name.text, n.initializer);
    ts.forEachChild(n, findHelpers);
  };
  findHelpers(sf);
  const stated = (r: string, seen: Set<string>): boolean => {
    if (ENVIRONMENT.has(r) || goldenExpectReads.has(r)) return true;
    const body = helpers.get(r) ?? loopBound.get(r);
    if (body === undefined || seen.has(r)) return false;
    seen.add(r);
    const reads = [...body].filter((x) => !ENVIRONMENT.has(x));
    return reads.length > 0 && reads.every((x) => stated(x, seen));
  };
  const out: string[] = [];
  for (const c of conditions) {
    const data = [...c.reads].filter((r) => !ENVIRONMENT.has(r));
    if (data.length === 0) continue;
    for (const r of data) if (!stated(r, new Set())) out.push(`${fileName}:${c.line} ${r}`);
  }
  return out;
}

describe("known answers", () => {
  const golden = (body: string): string => `describeGolden("g", () => { it("x", () => { ${body} }); });`;
  it("an unstated precondition is found; a stated one, an environment one and a file with no golden tier are not", () => {
    expect(unstatedPreconditions("a.test.ts", `const P = xs.length > 0;\nit.runIf(P)("t", () => {});\n${golden("expect(1).toBe(1);")}`)).toEqual(["a.test.ts:2 P"]);
    expect(unstatedPreconditions("a.test.ts", `it.runIf(P)("t", () => {});\n${golden("expect(P).toBe(true);")}`)).toEqual([]);
    expect(unstatedPreconditions("a.test.ts", `it.runIf(XS.length > 0)("t", () => {});\n${golden("expect(XS.length).toBeGreaterThan(0);")}`)).toEqual([]);
    expect(unstatedPreconditions("a.test.ts", `it.skipIf(!P)("t", () => {});\n${golden("expect(Q).toBe(true);")}`)).toEqual(["a.test.ts:1 P"]);
    expect(unstatedPreconditions("a.test.ts", `it.runIf(process.platform === "win32")("t", () => {});\n${golden("expect(1).toBe(1);")}`)).toEqual([]);
    expect(unstatedPreconditions("a.test.ts", `it.runIf(P)("t", () => {});`)).toEqual([]);
    // A helper stands for the table its body reads (less its parameters): stating the table states it.
    expect(unstatedPreconditions("a.test.ts", `const has = (k: string) => HAS[k];
it.runIf(has("x"))("t", () => {});
${golden("expect(HAS).toBeTruthy();")}`)).toEqual([]);
    expect(unstatedPreconditions("a.test.ts", `const has = (k: string) => HAS[k];
it.runIf(has("x"))("t", () => {});
${golden("expect(1).toBe(1);")}`)).toEqual(["a.test.ts:2 has"]);
    // A loop variable stands for its collection; a plain local computed from it does not (it must be stated).
    expect(unstatedPreconditions("a.test.ts", `for (const [t, pick] of CASES) it.runIf(pick())("t", () => {});
${golden("expect(CASES).toBeTruthy();")}`)).toEqual([]);
    expect(unstatedPreconditions("a.test.ts", `for (const c of CASES) { const rows = c.rows; it.runIf(rows.length > 0)("t", () => {}); }
${golden("expect(CASES).toBeTruthy();")}`)).toEqual(["a.test.ts:1 rows"]);
    // Read outside an expect(), or outside the golden block, does not count as stated.
    expect(unstatedPreconditions("a.test.ts", `it.runIf(P)("t", () => {});\nexpect(P).toBe(true);\n${golden("const q = P; expect(1).toBe(1);")}`)).toEqual(["a.test.ts:1 P"]);
  });
});

describe("every data precondition of a named skip is stated by the golden tier of its file", () => {
  const files = testFiles(SRC);
  const found = files.flatMap((f) => unstatedPreconditions(f.slice(SRC.length + 1).split("\\").join("/"), readFileSync(f, "utf8")));

  it("scanned the suite", () => {
    expect(files.length).toBeGreaterThan(100);
  });

  it("no runIf/skipIf precondition goes unstated on the reference sample", () => {
    expect(found).toEqual([]);
  });
});
