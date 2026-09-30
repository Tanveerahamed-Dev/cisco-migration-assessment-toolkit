/**
 * own-read.guard.test.ts — a dictionary keyed by names the SNAPSHOT supplies is read only through `own`.
 *
 * WHY (2026-09-30 refuter). c199e0f9 made the compiler safe for snapshot names such as "__proto__",
 * "constructor" and "toString"; the application kept reading the compiled dictionaries with `dict[name]`, which
 * answers a name the dictionary does not hold from the prototype chain. End to end on a renamed sample
 * (dataset.reserved-names.test.tsx) that threw in producer-emission and rib-completeness, counted a host with no
 * interface table as collected, and showed "0" ACL lines for a host whose ACLs were never collected. The fix is
 * one owner, `own` / `holds` in core/own.ts; this guard is what keeps every read going through it.
 *
 * WHAT IS A NAME-KEYED DICTIONARY — decided by the TYPE CHECKER, never by a list of property names. A dictionary
 * type carries the `NameKeyed` brand (core/types.ts). Which dictionaries must carry it is DERIVED: the guard walks
 * the compiled set's type (`CompiledDataset`, the compiler's output contract) and requires EVERY string-keyed
 * dictionary it reaches to be branded — so a dictionary added to the compiled documents without the brand fails
 * here, not in production.
 *
 * WHAT IS A READ, outside the owner, in every non-test `.ts`/`.tsx` under `src/` (the walk band-read.guard.test.ts
 * pins to vitest's globs):
 *   - `x[k]` / `x?.[k]` (read or write) where `x` carries the brand — a literal key too: one rule, no exceptions;
 *   - `k in x` where `x` carries the brand (`in` consults the prototype chain as well);
 *   - destructuring a branded value (`const { [host]: r } = fabric.routes`);
 *   - LAUNDERING: a type assertion (`as` / `<T>`) of a value whose type carries the brand anywhere inside it — the
 *     way two sidecar readers re-declared the documents under local, unbranded types and indexed those — and
 *     `x[k]` on an unbranded string-keyed dictionary whose value type IS a compiled dictionary's record type (a
 *     `Record<string, AclLine[]>` the branded value was assigned to).
 * What it cannot see is stated, not implied: a value laundered through `unknown` by assignment and re-typed by a
 * type predicate, or a dictionary of primitives (`Record<string, number>`) the brand was assigned away from. The
 * end-to-end test is the net under those.
 */
import { readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");
const TYPES = join(SRC, "core", "types.ts");
const OWNER = join(SRC, "core", "own.ts");
const DATASET_TYPES = join(SRC, "core", "dataset", "types.ts");

const norm = (p: string): string => resolve(p).split(sep).join("/").toLowerCase();
const ROOT_N = norm(ROOT);

/** Every authored module vitest's globs sit over: src/**, .ts/.tsx, not a test, no `_` segment. */
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
  const parsed = ts.parseJsonConfigFileContent(cfg.config, ts.sys, ROOT);
  return { ...parsed.options, noEmit: true };
}

export interface OwnRead {
  file: string;
  line: number;
  kind: "index" | "in" | "destructure" | "cast" | "laundered-index";
  text: string;
}
export interface CompiledDictionary {
  path: string;
  branded: boolean;
}

const PRIMITIVE =
  ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike | ts.TypeFlags.BigIntLike |
  ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Void | ts.TypeFlags.Never | ts.TypeFlags.ESSymbolLike;

/** The checker-side facts every check below reads: the brand, and the compiled dictionaries derived from the contract. */
const analysed = new WeakMap<ts.Program, ReturnType<typeof analyseOnce>>();
function analyse(program: ts.Program): ReturnType<typeof analyseOnce> {
  let a = analysed.get(program);
  if (a === undefined) {
    a = analyseOnce(program);
    analysed.set(program, a);
  }
  return a;
}
function analyseOnce(program: ts.Program) {
  const checker = program.getTypeChecker();
  const sfOf = (file: string): ts.SourceFile => {
    const sf = program.getSourceFiles().find((s) => norm(s.fileName) === norm(file));
    if (!sf) throw new Error(`${file} is not in the program — the guard cannot resolve the brand`);
    return sf;
  };
  /* The brand member: the one property of the type literal in `NameKeyed`'s intersection. */
  let brand: ts.Declaration | undefined;
  sfOf(TYPES).forEachChild((n) => {
    if (ts.isTypeAliasDeclaration(n) && n.name.text === "NameKeyed" && ts.isIntersectionTypeNode(n.type)) {
      for (const part of n.type.types) if (ts.isTypeLiteralNode(part)) brand = part.members[0];
    }
  });
  if (brand === undefined) throw new Error("NameKeyed's brand member was not found in core/types.ts");
  const brandDecl = brand;

  const parts = (t: ts.Type): readonly ts.Type[] => (t.isUnion() ? t.types : [t]);
  const carriesBrand = (t: ts.Type): boolean =>
    parts(t).some((c) => checker.getPropertiesOfType(checker.getApparentType(c)).some((p) => (p.declarations ?? []).includes(brandDecl)));

  /* ── the compiled dictionaries, derived by walking the compiled set's type ─────────────────── */
  let compiledSet: ts.Type | undefined;
  sfOf(DATASET_TYPES).forEachChild((n) => {
    if (ts.isTypeAliasDeclaration(n) && n.name.text === "CompiledDataset") compiledSet = checker.getTypeAtLocation(n.name);
  });
  if (compiledSet === undefined) throw new Error("CompiledDataset was not found in core/dataset/types.ts");
  const dictionaries: CompiledDictionary[] = [];
  /** The record types the compiled dictionaries hold (not primitives, not arrays of primitives). */
  const recordValueTypes = new Set<ts.Type>();
  const visited = new Set<ts.Type>();
  const visit = (t: ts.Type, path: string, depth: number): void => {
    if (depth > 10) return;
    for (const c of parts(t)) {
      if (c.flags & PRIMITIVE) continue;
      /* Every PATH that holds a dictionary is recorded; a type already walked is not walked again. */
      const info = checker.isArrayType(c) || checker.isTupleType(c) ? undefined : checker.getIndexInfoOfType(c, ts.IndexKind.String);
      if (info !== undefined) dictionaries.push({ path, branded: carriesBrand(c) });
      if (visited.has(c)) continue;
      visited.add(c);
      if (checker.isArrayType(c) || checker.isTupleType(c)) {
        for (const e of checker.getTypeArguments(c as ts.TypeReference)) visit(e, `${path}[]`, depth + 1);
        continue;
      }
      if (info !== undefined) {
        const v = info.type;
        const element = checker.isArrayType(v) ? checker.getTypeArguments(v as ts.TypeReference)[0] : v;
        if (element !== undefined && !parts(element).every((e) => e.flags & PRIMITIVE)) recordValueTypes.add(v);
        visit(v, `${path}.*`, depth + 1);
        continue;
      }
      for (const p of checker.getPropertiesOfType(c)) {
        if ((p.declarations ?? []).includes(brandDecl)) continue;
        visit(checker.getTypeOfSymbol(p), path === "" ? p.name : `${path}.${p.name}`, depth + 1);
      }
    }
  };
  visit(compiledSet, "", 0);

  /* ── "carries the brand anywhere inside it", for the laundering check ──────────────────────── */
  const ownTypeScript = (t: ts.Type): boolean =>
    (t.getSymbol()?.declarations ?? []).some((d) => {
      const f = norm(d.getSourceFile().fileName);
      return f.startsWith(`${ROOT_N}/`) && !f.includes("/node_modules/") && /\.(m?ts|tsx)$/.test(f);
    });
  const memo = new Map<ts.Type, boolean>();
  const containsBrand = (t: ts.Type, depth = 0): boolean => {
    if (depth > 6) return false;
    const hit = memo.get(t);
    if (hit !== undefined) return hit;
    memo.set(t, false);
    let out = carriesBrand(t);
    if (!out) {
      for (const c of parts(t)) {
        if (c.flags & PRIMITIVE) continue;
        if (checker.isArrayType(c)) {
          out = checker.getTypeArguments(c as ts.TypeReference).some((e) => containsBrand(e, depth + 1));
        } else if (c.isIntersection()) {
          out = c.types.some((e) => containsBrand(e, depth + 1));
        } else if (ownTypeScript(c)) {
          out = checker.getPropertiesOfType(c).some((p) => containsBrand(checker.getTypeOfSymbol(p), depth + 1));
        }
        if (out) break;
      }
    }
    memo.set(t, out);
    return out;
  };

  return { checker, carriesBrand, containsBrand, dictionaries, recordValueTypes, parts };
}

/** Every read of a name-keyed dictionary in `program`'s files that pass `consider`. Exported for the planted self-test. */
export function findOwnReads(program: ts.Program, consider: (fileName: string) => boolean): OwnRead[] {
  const { checker, carriesBrand, containsBrand, recordValueTypes, parts } = analyse(program);
  const receiverParts = (e: ts.Expression): readonly ts.Type[] => parts(checker.getNonNullableType(checker.getTypeAtLocation(e)));
  const launderedDictionary = (e: ts.Expression): boolean =>
    receiverParts(e).some((c) => {
      if (checker.isArrayType(c) || checker.isTupleType(c)) return false;
      const info = checker.getIndexInfoOfType(c, ts.IndexKind.String);
      return info !== undefined && recordValueTypes.has(info.type);
    });
  const out: OwnRead[] = [];
  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile || !consider(sf.fileName) || norm(sf.fileName) === norm(OWNER)) continue;
    const record = (node: ts.Node, kind: OwnRead["kind"]): void => {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      out.push({ file: sf.fileName, line: line + 1, kind, text: node.getText(sf).replace(/\s+/g, " ").slice(0, 120) });
    };
    const visit = (node: ts.Node): void => {
      if (ts.isElementAccessExpression(node)) {
        if (receiverParts(node.expression).some((c) => carriesBrand(c))) record(node, "index");
        else if (launderedDictionary(node.expression)) record(node, "laundered-index");
      } else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.InKeyword) {
        if (receiverParts(node.right).some((c) => carriesBrand(c))) record(node, "in");
      } else if (ts.isObjectBindingPattern(node)) {
        if (node.elements.some((el) => !el.dotDotDotToken) && carriesBrand(checker.getTypeAtLocation(node))) record(node, "destructure");
      } else if (
        ts.isBinaryExpression(node) &&
        node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
        ts.isObjectLiteralExpression(node.left)
      ) {
        if (carriesBrand(checker.getTypeAtLocation(node.right))) record(node, "destructure");
      } else if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)) {
        const asConst = ts.isConstTypeReference(node.type);
        if (!asConst && containsBrand(checker.getTypeAtLocation(node.expression))) record(node, "cast");
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return out;
}

/* The tree's program, built once and counted (band-read.guard.test.ts says why): one source file per case. */
let programsBuilt = 0;
let treeProgram: ts.Program | undefined;

describe("a name-keyed dictionary is read only through core/own.ts", () => {
  const files = walk(SRC);
  const program = (): ts.Program => {
    if (treeProgram === undefined) {
      programsBuilt += 1;
      treeProgram = ts.createProgram(files, compilerOptions());
    }
    return treeProgram;
  };
  const relOf = (f: string): string => relative(SRC, f).split(sep).join("/");

  it("walks every authored module under src/, including the owner and the known readers", () => {
    const rel = files.map(relOf);
    for (const must of [
      "core/own.ts",
      "core/data.ts",
      "core/acl-coverage.ts",
      "forwarding/engine.ts",
      "forwarding/rib-completeness.ts",
      "forwarding/bindings.ts",
      "panels/producer-emission.ts",
      "panels/DevicePane.tsx",
      "panels/EvidencePane.tsx",
      "panels/HopList.tsx",
      "panels/Inspector.tsx",
      "app/CoverageBar.tsx",
      "app/Header.tsx",
      "test-support/trace-universe.ts",
    ]) {
      expect(rel).toContain(must);
    }
    expect(files.length).toBeGreaterThan(60);
  });

  it("builds the tree's program (once: every per-file case below shares it)", () => {
    expect(program().getSourceFiles().filter((sf) => !sf.isDeclarationFile).length).toBeGreaterThanOrEqual(files.length);
  }, 120_000);

  it("every string-keyed dictionary the compiled documents carry is NameKeyed (derived from CompiledDataset)", () => {
    const { dictionaries } = analyse(program());
    const paths = dictionaries.map((d) => d.path);
    /* The walk reaches the dictionaries the refuter named, so the derivation is not vacuous. */
    for (const p of ["fabric.routes", "fabric.acls", "fabric.acls.*", "fabric.objectGroups", "fabric.interfaces", "aclBindings.hosts", "ribEvidence.hosts", "producerEmission.deviceAbsent", "producerEmission.aclLineAbsent"]) {
      expect(paths, p).toContain(p);
    }
    expect(dictionaries.filter((d) => !d.branded).map((d) => d.path)).toEqual([]);
  }, 60_000);

  it("the severity counts, keyed by a severity the snapshot supplies, are NameKeyed too", () => {
    const { checker, carriesBrand } = analyse(program());
    const sf = program().getSourceFiles().find((s) => norm(s.fileName) === norm(join(SRC, "core", "data.ts")))!;
    let decl: ts.Node | undefined;
    sf.forEachChild((n) => {
      if (ts.isVariableStatement(n)) for (const d of n.declarationList.declarations) if (ts.isIdentifier(d.name) && d.name.text === "severityCounts") decl = d.name;
    });
    expect(decl, "severityCounts is not declared in core/data.ts").toBeDefined();
    const sig = checker.getSignaturesOfType(checker.getTypeAtLocation(decl!), ts.SignatureKind.Call)[0]!;
    expect(carriesBrand(checker.getReturnTypeOfSignature(sig))).toBe(true);
  });

  for (const file of files) {
    if (norm(file) === norm(OWNER)) continue;
    it(`${relOf(file)}: reads no name-keyed dictionary except through core/own.ts`, () => {
      expect(findOwnReads(program(), (f) => norm(f) === norm(file)).map((r) => `${relOf(r.file)}:${r.line} [${r.kind}] ${r.text}`)).toEqual([]);
    });
  }

  it("built the tree's program at most once for all of the cases above", () => {
    expect(programsBuilt, "the program was built more than once").toBeLessThanOrEqual(1);
  });

  it("is live: a planted module reading a compiled dictionary every way it can be read is flagged, and own() is not", () => {
    const planted = join(SRC, "core", "__planted_own_reader.ts").split(sep).join("/");
    const source = [
      `import type { AclLine, Fabric, NameKeyed } from "./types";`,
      `export function a(f: Fabric, h: string) { return f.routes[h]; }`,
      `export function b(f: Fabric, h: string) { return h in f.interfaces; }`,
      `export function c(f: Fabric, h: string) { const { [h]: x } = f.acls; return x; }`,
      `export function d(t: NameKeyed<number> | undefined, k: string) { return t?.[k]; }`,
      `export function e(f: Fabric) { return (f.objectGroups as unknown as Record<string, unknown>)["core1"]; }`,
      `export function g(named: Record<string, AclLine[]>, n: string) { return named[n]; }`,
      // NOT a compiled dictionary: a dictionary of numbers the application builds for itself.
      `export function h(m: Record<string, number>, k: string) { return m[k]; }`,
      `import { own } from "./own";`,
      `export function i(f: Fabric, h: string) { return own(own(f.acls, h), "MGMT_IN"); }`,
      `export function j(f: Fabric) { return f.coverage.aclSummary["n_findings"]; }`,
    ].join("\n");
    const opts = compilerOptions();
    const host = ts.createCompilerHost(opts);
    const origGet = host.getSourceFile.bind(host);
    host.getSourceFile = (name, lang, onErr, create) =>
      norm(name) === norm(planted) ? ts.createSourceFile(name, source, lang, true, ts.ScriptKind.TS) : origGet(name, lang, onErr, create);
    const origExists = host.fileExists.bind(host);
    host.fileExists = (name) => norm(name) === norm(planted) || origExists(name);
    const p = ts.createProgram([planted, TYPES, OWNER, DATASET_TYPES], opts, host);
    const reads = findOwnReads(p, (f) => norm(f) === norm(planted));
    /* Lines 2-7 and 11 read a compiled dictionary (7 through a laundered Record<string, AclLine[]>); line 8 reads an
       unrelated dictionary and line 10 reads through the owner — neither may be flagged. */
    expect([...new Set(reads.map((r) => r.line))].sort((x, y) => x - y)).toEqual([2, 3, 4, 5, 6, 7, 11]);
    expect(reads.find((r) => r.line === 6)?.kind).toBe("cast");
    expect(reads.find((r) => r.line === 7)?.kind).toBe("laundered-index");
  }, 120_000);
});
