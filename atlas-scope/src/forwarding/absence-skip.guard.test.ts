// @vitest-environment node
/**
 * absence-skip.guard.test.ts — an invariant test whose subject is ABSENT on the loaded fabric says so by name
 * (test-subjects.ts `need()` → a not-applicable skip), never by an early `return` that the runner counts as a
 * pass (phase-3.5 V2-m1).
 *
 * The defect shape: `if (s === undefined) { expect(...).not.toContain(...); return; }` inside an `it()`. On a
 * fabric without the subject the test reports PASSED although all it asserted was the absence, so a leg
 * report cannot tell "checked and held" from "had nothing to check". The rule is structural — any test body
 * in the owned invariant tiers whose top-level `if` tests a value against `undefined`/`null` and returns —
 * not a list of today's test names.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const PKG = resolve(__dirname, "..", "..");
const posix = (p: string): string => p.split("\\").join("/");

/** Is `n` a comparison of something against `undefined` / `null` (either side, strict or loose)? */
function testsAbsence(n: ts.Node): boolean {
  let hit = false;
  const visit = (x: ts.Node): void => {
    if (ts.isBinaryExpression(x)) {
      const op = x.operatorToken.kind;
      if (
        op === ts.SyntaxKind.EqualsEqualsEqualsToken ||
        op === ts.SyntaxKind.EqualsEqualsToken
      ) {
        const isAbsent = (e: ts.Expression): boolean =>
          e.kind === ts.SyntaxKind.NullKeyword || (ts.isIdentifier(e) && e.text === "undefined");
        if (isAbsent(x.left) || isAbsent(x.right)) hit = true;
      }
    }
    if (!hit) ts.forEachChild(x, visit);
  };
  visit(n);
  return hit;
}

/** Does the branch end by returning (a bare `return;` or a block whose last statement returns)? */
function endsInReturn(s: ts.Statement): boolean {
  if (ts.isReturnStatement(s)) return true;
  if (ts.isBlock(s)) {
    const last = s.statements[s.statements.length - 1];
    return last !== undefined && ts.isReturnStatement(last);
  }
  return false;
}

/** Does the branch name its skip (`need(...)`, `needSome(...)`, `<ctx>.skip(...)`)? */
function namesItsSkip(s: ts.Node): boolean {
  let hit = false;
  const visit = (x: ts.Node): void => {
    if (ts.isCallExpression(x)) {
      const e = x.expression;
      if (ts.isIdentifier(e) && (e.text === "need" || e.text === "needSome")) hit = true;
      if (ts.isPropertyAccessExpression(e) && e.name.text === "skip") hit = true;
    }
    if (!hit) ts.forEachChild(x, visit);
  };
  visit(s);
  return hit;
}

/** The identifiers the absence condition compares (`s === undefined` → `s`). */
function absentNames(n: ts.Node): Set<string> {
  const out = new Set<string>();
  const visit = (x: ts.Node): void => {
    if (ts.isIdentifier(x) && x.text !== "undefined") out.add(x.text);
    ts.forEachChild(x, visit);
  };
  visit(n);
  return out;
}

/** Is `st` an assertion that FAILS when one of `names` is absent (`expect(s).toBeDefined()`, `.not.toBeNull()`, …)? */
function assertsPresence(st: ts.Statement | undefined, names: Set<string>): boolean {
  if (st === undefined || !ts.isExpressionStatement(st) || !ts.isCallExpression(st.expression)) return false;
  const call = st.expression;
  if (!ts.isPropertyAccessExpression(call.expression)) return false;
  const matcher = call.expression.name.text;
  let target: ts.Expression = call.expression.expression;
  let negated = false;
  if (ts.isPropertyAccessExpression(target) && target.name.text === "not") {
    negated = true;
    target = target.expression;
  }
  const failsOnAbsence = negated ? matcher === "toBeNull" || matcher === "toBeUndefined" : matcher === "toBeDefined" || matcher === "toBeTruthy";
  if (!failsOnAbsence || !ts.isCallExpression(target) || !ts.isIdentifier(target.expression) || target.expression.text !== "expect") return false;
  const subject = target.arguments[0];
  return subject !== undefined && ts.isIdentifier(subject) && names.has(subject.text);
}

const TEST_CALLEES = new Set(["it", "test"]);

/** Every `it(...)`/`test(...)` body in a source text, with each top-level early return on an absent value. */
function vacuousAbsencePasses(fileName: string, text: string): string[] {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.ES2023, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n)) {
      const callee = n.expression;
      const base = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) && ts.isIdentifier(callee.expression) ? callee.expression.text : null;
      const body = n.arguments.find((a): a is ts.ArrowFunction | ts.FunctionExpression => ts.isArrowFunction(a) || ts.isFunctionExpression(a));
      if (base !== null && TEST_CALLEES.has(base) && body !== undefined && ts.isBlock(body.body)) {
        const name = n.arguments[0] && ts.isStringLiteralLike(n.arguments[0]) ? n.arguments[0].text : "<unnamed>";
        const statements = body.body.statements;
        for (const [i, st] of statements.entries()) {
          if (!ts.isIfStatement(st)) continue;
          /* Lawful: the branch names its skip, or the statement before it already FAILED the test on absence
             (the `return` is then only a type narrowing). Anything else is a pass that checked nothing. */
          const failedAlready = assertsPresence(statements[i - 1], absentNames(st.expression));
          if (testsAbsence(st.expression) && endsInReturn(st.thenStatement) && !namesItsSkip(st.thenStatement) && !failedAlready) {
            const line = sf.getLineAndCharacterOfPosition(st.getStart(sf)).line + 1;
            out.push(`${fileName}:${line} — "${name}"`);
          }
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

/** The invariant tiers this rule governs: every forwarding test, every panels test, and the flow-terminal sweep. */
function governedFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.test\.tsx?$/.test(name)) out.push(p);
    }
  };
  walk(resolve(PKG, "src", "forwarding"));
  walk(resolve(PKG, "src", "panels"));
  out.push(resolve(PKG, "src", "fabric3d", "flow-terminal.counterfactual.test.ts"));
  return out.sort();
}

/** An IPv4 address or prefix written into a literal — dotted, or underscore-encoded as in an intent id. */
const ADDRESS_IN_LITERAL = /(?:^|[^\d])\d{1,3}[._]\d{1,3}[._]\d{1,3}[._]\d{1,3}(?:[^\d]|$)/;

/** Every `need(...)` / `needSome(...)` whose SUBJECT argument is looked up by a literal naming an address. */
function subjectsKeyedByAddress(fileName: string, text: string): string[] {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.ES2023, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && (n.expression.text === "need" || n.expression.text === "needSome")) {
      const subject = n.arguments[1];
      if (subject !== undefined) {
        const lits: string[] = [];
        const scan = (x: ts.Node): void => {
          if (ts.isStringLiteral(x) || ts.isNoSubstitutionTemplateLiteral(x) || ts.isTemplateHead(x) || ts.isTemplateMiddle(x) || ts.isTemplateTail(x)) lits.push(x.text);
          ts.forEachChild(x, scan);
        };
        scan(subject);
        const hit = lits.find((l) => ADDRESS_IN_LITERAL.test(l));
        if (hit !== undefined) out.push(`${fileName}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1} — "${hit}"`);
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

describe("a property subject is found by its property, never by a sample address (P3B-R2-m2)", () => {
  it("the scanner recognises a subject keyed by an address literal (planted, not assumed)", () => {
    const planted = [
      'const a = need(ctx, catalog.find((i) => i.id === "no-reach-10_0_20_0_24-10_0_30_0_24"), "x");',
      'const b = need(ctx, flows.find((f) => f.dstIp === "10.0.30.10"), "y");',
      'const c = need(ctx, catalog.find((i) => i.kind === "none-reach"), "a none-reach intent from 10.0.30.50");',
      'const d = need(ctx, preset("multi-hop-denial"), "z");',
    ].join("\n");
    expect(subjectsKeyedByAddress("planted.test.ts", planted)).toEqual([
      'planted.test.ts:1 — "no-reach-10_0_20_0_24-10_0_30_0_24"',
      'planted.test.ts:2 — "10.0.30.10"',
    ]);
  });

  it("no governed test resolves a need() subject through a sample address", () => {
    const hits = governedFiles().flatMap((f) => subjectsKeyedByAddress(posix(relative(PKG, f)), readFileSync(f, "utf8")));
    expect(hits).toEqual([]);
  });
});

describe("an absent subject is a named not-applicable skip, never a pass (V2-m1)", () => {
  it("the scanner recognises the defect shape and its lawful forms (planted, not assumed)", () => {
    const planted = [
      'it("vacuous", () => { const s = find(); if (s === undefined) { expect(1).toBe(1); return; } use(s); });',
      'it("vacuous null", () => { const s = find(); if (null == s) return; use(s); });',
      'it("named", (ctx) => { const s = find(); if (s === undefined) { need(ctx, s, "x"); return; } use(s); });',
      'it("skip", (ctx) => { const s = find(); if (s === null) { ctx.skip("x"); return; } use(s); });',
      'it("throws", () => { const s = find(); if (s === undefined) throw new Error("x"); use(s); });',
      'it("nested helper", () => { [1].forEach((h) => { if (h === null) return; }); });',
      'it("failed already", () => { const s = find(); expect(s, "precondition").toBeDefined(); if (s === undefined) return; use(s); });',
      'it("asserts another", () => { const s = find(); expect(t).toBeDefined(); if (s === undefined) return; use(s); });',
    ].join("\n");
    const hits = vacuousAbsencePasses("planted.test.ts", planted);
    expect(hits).toEqual(['planted.test.ts:1 — "vacuous"', 'planted.test.ts:2 — "vacuous null"', 'planted.test.ts:8 — "asserts another"']);
  });

  it("no governed invariant test returns early on an absent subject", () => {
    const files = governedFiles();
    expect(files.length, "the governed tiers were found").toBeGreaterThan(40);
    const hits = files.flatMap((f) => vacuousAbsencePasses(posix(relative(PKG, f)), readFileSync(f, "utf8")));
    expect(hits).toEqual([]);
  });
});
