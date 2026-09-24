/**
 * verdict-wording.guard.test.ts — a forwarding verdict is put into words only by its owners.
 *
 * WHY A PARSER GUARD. B2 went PASS → FAIL without the engine changing: the engine attached a scope
 * clause and 8–13 caveats to every verdict, and the command palette re-worded the same verdicts from
 * the bare outcome enum — `trace a path — this one ends ${flow.expectedOutcome}`,
 * `${formatFlow(s.flow)} — ${s.expectedOutcome}. ${s.rationale}` — so the words reached the screen
 * without the claim that bounded them, and an undecided denial read as a decided one. The Path
 * presets did the same through a second outcome→word table. A list of the surfaces that re-word a
 * verdict is the defect shape this repository keeps producing; the next surface is never on it.
 *
 * So the invariant is stated about the CLASS: outside the owners, no value of type `TraceOutcome`
 * becomes text. "Becomes text" is structural — the value sits inside a template-literal
 * substitution, a JSX child, or a `+` with a string — and "of type TraceOutcome" is resolved by the
 * TYPE CHECKER, never by a property name, so `const o = t.outcome; \`${o}\`` and a local helper
 * `w(t.outcome)` are both found. A call into an owner (`outcomeWordOf(t)`,
 * `outcomeTallyWord(k, …)`) is the sanctioned door and is not descended into; a call into anything
 * else is. A second outcome→word table — any declaration whose type is a mapping keyed by
 * `TraceOutcome` onto strings — is the same defect one step removed and is flagged too.
 *
 * THE OWNERS, and why each is one:
 *   - `src/forwarding/engine.ts` — it writes the claim sentence the verdict travels in;
 *   - `src/core/claims.ts` — the band, badge, undecided-word and literal-template owner;
 *   - `src/panels/ClaimCard.tsx` — the one surface that renders a verdict as one object with its
 *     scope and caveats, and the home of `outcomeWordOf` / `verdictStatement`, the words every other
 *     surface borrows.
 *
 * The denominator is every non-test `.ts`/`.tsx` under `src/` that vitest's globs sit over. The guard
 * proves itself live inside the suite: a planted in-memory module that re-words a verdict seven
 * ways is flagged on exactly those lines, and its four sanctioned forms are not.
 */
import { readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");
const TYPES = join(SRC, "core", "types.ts");
const OWNERS = [join(SRC, "forwarding", "engine.ts"), join(SRC, "core", "claims.ts"), join(SRC, "panels", "ClaimCard.tsx")];

const norm = (p: string): string => resolve(p).split(sep).join("/").toLowerCase();
const OWNER_SET = new Set(OWNERS.map(norm));
const rel = (p: string): string => relative(SRC, p).split(sep).join("/");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name.startsWith("_")) continue; // vitest.config.ts: "src/**/_*/**", "src/**/_*"
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if ([".ts", ".tsx"].includes(extname(p)) && !/\.test\.tsx?$/.test(p) && !p.endsWith(".d.ts")) out.push(p);
  }
  return out;
}

function compilerOptions(): ts.CompilerOptions {
  const cfg = ts.readConfigFile(join(ROOT, "tsconfig.json"), ts.sys.readFile);
  if (cfg.error) throw new Error(ts.flattenDiagnosticMessageText(cfg.error.messageText, "\n"));
  return { ...ts.parseJsonConfigFileContent(cfg.config, ts.sys, ROOT).options, noEmit: true };
}

export interface VerdictWording {
  file: string;
  line: number;
  /** The flagged expression. */
  text: string;
  /** The whole source line it sits on, trimmed — what a pending-fix ledger entry is pinned to. */
  source: string;
  kind: "outcome-as-text" | "outcome-word-table";
}

/**
 * Every place in `program`'s files that pass `consider` where a `TraceOutcome` becomes text, or a
 * second outcome→word table is declared. Owners are not exempted here: the caller decides.
 */
export function findVerdictWording(program: ts.Program, consider: (fileName: string) => boolean): VerdictWording[] {
  const checker = program.getTypeChecker();
  const typesSf = program.getSourceFiles().find((sf) => norm(sf.fileName) === norm(TYPES));
  if (!typesSf) throw new Error("types.ts is not in the program — the guard cannot resolve TraceOutcome");
  let alias: ts.TypeAliasDeclaration | undefined;
  typesSf.forEachChild((n) => {
    if (ts.isTypeAliasDeclaration(n) && n.name.text === "TraceOutcome") alias = n;
  });
  if (!alias) throw new Error("TraceOutcome not found in types.ts");
  const outcomeType = checker.getTypeAtLocation(alias.name);
  // The member set is READ from the type, never written down here.
  const members = new Set(
    (outcomeType.isUnion() ? outcomeType.types : [outcomeType]).flatMap((t) => (t.isStringLiteral() ? [t.value] : [])),
  );
  if (members.size === 0) throw new Error("TraceOutcome resolved to no string-literal members");

  const isOutcomeTyped = (t: ts.Type): boolean => {
    const parts = t.isUnion() ? t.types : [t];
    return parts.length > 0 && parts.every((p) => p.isStringLiteral() && members.has(p.value));
  };
  const declaredInOwner = (call: ts.CallExpression): boolean => {
    const sym = checker.getSymbolAtLocation(ts.isPropertyAccessExpression(call.expression) ? call.expression.name : call.expression);
    const target = sym && sym.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(sym) : sym;
    const decls = target?.declarations ?? [];
    return decls.length > 0 && decls.every((d) => OWNER_SET.has(norm(d.getSourceFile().fileName)));
  };

  const out: VerdictWording[] = [];
  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile || !consider(sf.fileName)) continue;
    const lines = sf.getFullText().split(/\r?\n/);
    const flagged = new Set<ts.Node>();
    const record = (node: ts.Node, kind: VerdictWording["kind"]): void => {
      if (flagged.has(node)) return;
      flagged.add(node);
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      out.push({
        file: sf.fileName,
        line: line + 1,
        text: node.getText(sf).replace(/\s+/g, " ").slice(0, 120),
        source: (lines[line] ?? "").trim(),
        kind,
      });
    };

    /** Inside a text position: find every TraceOutcome-typed expression that reaches the text. */
    const scan = (node: ts.Node): void => {
      if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)) return; // a literal is the author's word, not a value
      if (ts.isCallExpression(node) && declaredInOwner(node)) return; // the sanctioned door
      if (ts.isJsxAttribute(node)) return; // an attribute is not text (data-outcome=…)
      if (ts.isExpression(node) && !ts.isTemplateExpression(node) && isOutcomeTyped(checker.getTypeAtLocation(node))) {
        // A comparison's operands are typed TraceOutcome but the comparison is not: `x === "denied"`
        // is boolean, so it is reached only through what it selects, which is scanned below.
        record(node, "outcome-as-text");
        return;
      }
      ts.forEachChild(node, scan);
    };

    const isStringish = (n: ts.Expression): boolean => {
      const t = checker.getTypeAtLocation(n);
      return (t.flags & ts.TypeFlags.StringLike) !== 0 || (t.isUnion() && t.types.every((p) => (p.flags & ts.TypeFlags.StringLike) !== 0));
    };

    const visit = (node: ts.Node): void => {
      if (ts.isTemplateSpan(node)) {
        scan(node.expression);
      } else if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
        scan(node.expression);
      } else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken && (isStringish(node.left) || isStringish(node.right))) {
        scan(node.left);
        scan(node.right);
      } else if (ts.isVariableDeclaration(node) || ts.isPropertyDeclaration(node)) {
        // A second outcome→word table: a value whose type maps every TraceOutcome onto a string.
        const t = checker.getTypeAtLocation(node.name);
        const props = checker.getPropertiesOfType(t);
        const keys = new Set(props.map((p) => p.name));
        if (props.length > 0 && keys.size === members.size && [...members].every((m) => keys.has(m))) {
          const valuesAreText = props.every((p) => {
            const pt = checker.getTypeOfSymbolAtLocation(p, node);
            return (pt.flags & ts.TypeFlags.StringLike) !== 0;
          });
          if (valuesAreText) record(node.name, "outcome-word-table");
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return out;
}

/**
 * Pending fixes in files this change could not edit. Each entry is pinned to the exact source line,
 * and the guard FAILS when an entry no longer matches anything — so the ledger can only shrink, and
 * cannot quietly absorb a new offender (a new one is a different line, which is not in it).
 */
const PENDING_OUTSIDE_OWNER: readonly { file: string; source: string; owner: string }[] = [];

describe("a forwarding verdict is put into words only by its owners (B2 structural guard)", () => {
  const files = walk(SRC);

  it("walks the whole authored tree, and the owners are in it", () => {
    const r = files.map(rel);
    for (const o of OWNERS) expect(r).toContain(rel(o));
    for (const must of ["app/commands.ts", "app/CommandPalette.tsx", "panels/PathTrace.tsx", "app/App.tsx"]) expect(r).toContain(must);
    expect(files.length).toBeGreaterThan(60);
  });

  it("finds no verdict put into words outside the owners", () => {
    const program = ts.createProgram(files, compilerOptions());
    const inTree = new Set(files.map(norm));
    const found = findVerdictWording(program, (f) => inTree.has(norm(f)));
    // The owners do word verdicts — which also proves the resolver resolves on the real tree.
    expect(found.some((w) => OWNER_SET.has(norm(w.file)))).toBe(true);
    const outside = found.filter((w) => !OWNER_SET.has(norm(w.file)));
    const pending = outside.filter((w) => PENDING_OUTSIDE_OWNER.some((p) => p.file === rel(w.file) && p.source === w.source));
    const offenders = outside.filter((w) => !pending.includes(w)).map((w) => `${rel(w.file)}:${w.line} [${w.kind}] ${w.text}  ::  ${w.source}`);
    expect(offenders).toEqual([]);
    // The ledger expires: an entry that matches nothing has been fixed (or moved) and must go.
    const stale = PENDING_OUTSIDE_OWNER.filter((p) => !pending.some((w) => rel(w.file) === p.file && w.source === p.source));
    expect(stale.map((p) => `${p.file}: ${p.source}`), "a pending-fix entry no longer matches its line: delete it").toEqual([]);
  }, 120_000);

  it("is live: a planted module re-wording a verdict seven ways is flagged on exactly those lines", () => {
    const planted = join(SRC, "app", "__planted_verdict_wording.tsx").split(sep).join("/");
    const source = [
      /* 1 */ `import type { Trace, TraceOutcome } from "../core/types";`,
      /* 2 */ `import { outcomeWordOf } from "../panels/ClaimCard";`,
      /* 3 */ `export const a = (t: Trace) => \`trace a path — this one ends \${t.outcome}\`;`,
      /* 4 */ `export const b = (zq: { expectedOutcome: TraceOutcome }) => <span>{zq.expectedOutcome}</span>;`,
      /* 5 */ `export const c = (t: Trace) => "ends " + t.outcome;`,
      /* 6 */ `const WORDS: Record<TraceOutcome, string> = { delivered: "d", dropped: "x", denied: "n", indeterminate: "i", "out-of-scope": "o" };`,
      /* 7 */ `const w = (o: TraceOutcome) => o;`,
      /* 8 */ `export const d = (t: Trace) => { const o = t.outcome; return \`\${o} and \${w(t.outcome)}\`; };`,
      /* 9 */ `export const e = (t: Trace) => \`\${outcomeWordOf(t)} — sanctioned\`;`,
      /* 10 */ `export const f = (t: Trace) => <i data-outcome={t.outcome}>x</i>;`,
      /* 11 */ `export const g = () => \`the literal word denied is the author's\`;`,
      /* 12 */ `export const h = (t: Trace) => WORDS[t.outcome].length;`,
      /* 13 */ `export const k = (t: Trace) => <b>{t.outcome === "denied" ? "blocked" : "passed"}</b>;`,
    ].join("\n");
    const opts = compilerOptions();
    const host = ts.createCompilerHost(opts);
    const origGet = host.getSourceFile.bind(host);
    host.getSourceFile = (name, lang, onErr, create) =>
      norm(name) === norm(planted) ? ts.createSourceFile(name, source, lang, true, ts.ScriptKind.TSX) : origGet(name, lang, onErr, create);
    const origExists = host.fileExists.bind(host);
    host.fileExists = (name) => norm(name) === norm(planted) || origExists(name);
    const program = ts.createProgram([planted, TYPES, ...OWNERS], opts, host);
    const found = findVerdictWording(program, (f) => norm(f) === norm(planted));
    const lines = [...new Set(found.map((w) => w.line))].sort((p, q) => p - q);
    // 3 template, 4 JSX child, 5 concatenation, 6 a second word table, 8 an aliased value AND a
    // non-owner helper, 13 words CHOSEN by the outcome. Line 9 goes through the owner, line 10's
    // outcome is an attribute, 11 is a literal, 12 is not text — none of those is flagged.
    expect(lines).toEqual([3, 4, 5, 6, 8, 13]);
    expect(found.filter((w) => w.line === 8).map((w) => w.text).sort()).toEqual(["o", "w(t.outcome)"]);
  }, 120_000);
});
