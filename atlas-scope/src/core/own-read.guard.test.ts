/**
 * own-read.guard.test.ts — DEFENCE IN DEPTH around core/own.ts. The structural guarantee is at run time; this guard
 * is the type-checker net over the source, and it states exactly what it can and cannot see.
 *
 * WHY (2026-09-30 refuter, rounds 2 and 3). c199e0f9 made the compiler safe for snapshot names such as "__proto__",
 * "constructor" and "toString"; the application kept reading the compiled dictionaries with `dict[name]`, which
 * answers a name the dictionary does not hold from the prototype chain (dataset.reserved-names.test.tsx). The first
 * version of this guard trusted DECLARED TYPES, and a refuter then read a compiled dictionary past it seven ways
 * (`Reflect.get`, a generic helper over `Record<string, T>`, plain assignment to a wider dictionary type or to `any`,
 * a JSON round trip), and indexed CONSTANT TABLES by snapshot values (a category, a band, a severity, a kind) that no
 * dictionary brand could mark. So:
 *
 * THE STRUCTURAL GUARANTEE is not this file. `core/dataset.ts` hands the one installed set to `withoutPrototypes`
 * (core/own.ts), so every name-keyed compiled dictionary has NO prototype and every read shape — this guard's
 * blind spots included — sees only own entries; `dataset.reserved-names.test.tsx` plants the refuter's read shapes
 * against a renamed sample and fails if that call is removed. The closed vocabularies are honest in the TYPE
 * (core/types.ts `Unrecognised`): a snapshot severity, band or kind cannot index a table typed by its union without
 * the recogniser, and `dataset.unrecognised-values.test.tsx` renders every surface for such values.
 *
 * WHAT THIS GUARD DERIVES (never a list of names). The brand member of `NameKeyed` and of `Unrecognised` are found
 * in core/types.ts; the compiled dictionaries are found by walking `CompiledDataset` (every path, each type re-walked
 * on every path it occurs on, cycles cut by the ancestor chain) — every one must carry the brand, and
 * `COMPILED_NAME_KEYED_PATHS`, the run-time list `withoutPrototypes` walks, must equal the derived paths exactly.
 *
 * WHAT IS FLAGGED, outside core/own.ts, in every non-test `.ts`/`.tsx` under `src/` (the walk band-read.guard.test.ts
 * pins to vitest's globs):
 *   index           `x[k]` / `x?.[k]` where `x` carries the NameKeyed brand — any key, read or write;
 *   in              `k in x` where `x` carries the brand;
 *   destructure     a computed or named binding out of a branded value;
 *   cast            a type assertion of a value whose type carries the brand anywhere inside it;
 *   laundered-index `x[k]` on an unbranded dictionary whose value type IS a compiled dictionary's record type;
 *   wide-index      a READ (compound assignment and `??=` included) of ANY string-indexed dictionary — a compiled one
 *                   re-typed, a generic helper's `Record<string, T>`, a constant table, one the application built —
 *                   by a key whose type is not a string literal (`string`, a template, a branded string): this is what
 *                   makes a constant table indexed by a snapshot value go through `own`;
 *   wide-in         `k in x` on such a dictionary with such a key;
 *   any-index       `x[k]` where `x` is `any` and `k` is not a literal (a JSON.parse result, an any-cast);
 *   hand-rolled     `hasOwnProperty`, `Object.hasOwn`, `Object/Reflect.getOwnPropertyDescriptor`, `Reflect.get`,
 *                   `Reflect.has` — a second copy of the owner's rule, or a read around it;
 *   copy            `JSON.parse(JSON.stringify(x))` where `x` carries the brand anywhere inside it: the copy is an
 *                   ordinary object again, which no run-time structure follows (core/own.ts, A COPY IS AN ORDINARY
 *                   OBJECT AGAIN), and its type is `any`, so the round trip itself is forbidden — and any read of its
 *                   result by a non-literal key is `any-index` besides. (`structuredClone` keeps the static type, so
 *                   a read of its result is `index`; the one legitimate clone, the store's copy of a set BEFORE the
 *                   door, is never read as a dictionary before `withoutPrototypes` runs on it.)
 *   construct       an object literal or `Object.fromEntries`/`Object.assign`/`Object.create` call contextually typed
 *                   as a NameKeyed dictionary — the application builds one only with `nameKeyed` (no prototype);
 *   vocabulary-cast a type assertion that drops the `Unrecognised` brand from a closed-vocabulary value (to anything
 *                   but plain `string`), which is how a `Severity` table would be indexed with an unchecked severity.
 *
 * WHAT IT CANNOT SEE, stated rather than implied — each is covered by the run-time structure above, or is not a read:
 * a value laundered through `unknown` by ASSIGNMENT and re-typed by a type predicate; a dictionary reached through a
 * callback's `any`-less inference the checker resolves to a non-dictionary type; aliases of the reflective APIs
 * (`const { hasOwn } = Object`); plain `x[k] = v` WRITES to an unbranded dictionary (the compiler's DICTIONARY RULE
 * owns snapshot-keyed writes; the application writes only into `nameKeyed` dictionaries and Maps); copies made with
 * spread, `Object.assign`, `Object.fromEntries` or `structuredClone` are caught at their READ (their type keeps the
 * brand, or is a string-indexed dictionary read by a wide key), not at the copy; a WIDE STRING asserted to a literal
 * union (`s as keyof typeof TABLE`) and then used as a literal key — ten such casts exist today (UI tabs, sort fields,
 * the flow protocol), none on a compiled value, and the closed-vocabulary fields cannot reach one without a
 * vocabulary-cast; and anything outside `src/` (tools/ and the compiler follow THE DICTIONARY RULE in
 * tools/lib/compile-model.mjs, pinned by compile-reserved-names.test.ts).
 */
import { readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { COMPILED_NAME_KEYED_PATHS } from "./own";

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

export type OwnReadKind =
  | "index"
  | "in"
  | "destructure"
  | "cast"
  | "laundered-index"
  | "wide-index"
  | "wide-in"
  | "any-index"
  | "hand-rolled"
  | "copy"
  | "construct"
  | "vocabulary-cast";
export interface OwnRead {
  file: string;
  line: number;
  kind: OwnReadKind;
  text: string;
}
export interface CompiledDictionary {
  path: string;
  branded: boolean;
}

const PRIMITIVE =
  ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike | ts.TypeFlags.BigIntLike |
  ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Void | ts.TypeFlags.Never | ts.TypeFlags.ESSymbolLike;

/** The member of the type literal a brand alias (`X = … & { readonly [SYM]?: … }`) intersects in. */
function brandMember(sf: ts.SourceFile, alias: string): ts.Declaration {
  let brand: ts.Declaration | undefined;
  sf.forEachChild((n) => {
    if (ts.isTypeAliasDeclaration(n) && n.name.text === alias && ts.isIntersectionTypeNode(n.type)) {
      for (const part of n.type.types) if (ts.isTypeLiteralNode(part)) brand = part.members[0];
    }
  });
  if (brand === undefined) throw new Error(`${alias}'s brand member was not found in core/types.ts`);
  return brand;
}

/** The checker-side facts every check below reads: the brands, and the compiled dictionaries derived from the contract. */
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
  const brandDecl = brandMember(sfOf(TYPES), "NameKeyed");
  const unrecognisedDecl = brandMember(sfOf(TYPES), "Unrecognised");

  const parts = (t: ts.Type): readonly ts.Type[] => (t.isUnion() ? t.types : [t]);
  const hasMember = (t: ts.Type, decl: ts.Declaration): boolean =>
    parts(t).some((c) => checker.getPropertiesOfType(checker.getApparentType(c)).some((p) => (p.declarations ?? []).includes(decl)));
  const carriesBrand = (t: ts.Type): boolean => hasMember(t, brandDecl);
  const carriesUnrecognised = (t: ts.Type): boolean =>
    parts(t).some((c) => (c.isIntersection() ? c.types : [c]).some((p) => hasMember(p, unrecognisedDecl)));

  /* ── the compiled dictionaries, derived by walking the compiled set's type ─────────────────── */
  let compiledSet: ts.Type | undefined;
  sfOf(DATASET_TYPES).forEachChild((n) => {
    if (ts.isTypeAliasDeclaration(n) && n.name.text === "CompiledDataset") compiledSet = checker.getTypeAtLocation(n.name);
  });
  if (compiledSet === undefined) throw new Error("CompiledDataset was not found in core/dataset/types.ts");
  const dictionaries: CompiledDictionary[] = [];
  /** Every compiled field whose type is (or includes) a closed vocabulary — a union of string literals. */
  const closedFields: { path: string; unrecognised: boolean }[] = [];
  /** The record types the compiled dictionaries hold (not primitives, not arrays of primitives). */
  const recordValueTypes = new Set<ts.Type>();
  /* Every PATH is walked: a type met again on another path is walked again there (a dictionary type shared by two
     documents is two run-time dictionaries); only a type already on the current ancestor chain is not (a cycle). */
  const visit = (t: ts.Type, path: string, ancestors: readonly ts.Type[]): void => {
    if (ancestors.length > 12) return;
    if (parts(t).some((c) => (c.flags & ts.TypeFlags.StringLiteral) !== 0)) closedFields.push({ path, unrecognised: carriesUnrecognised(t) });
    for (const c of parts(t)) {
      if (c.flags & PRIMITIVE) continue;
      const info = checker.isArrayType(c) || checker.isTupleType(c) ? undefined : checker.getIndexInfoOfType(c, ts.IndexKind.String);
      if (info !== undefined) dictionaries.push({ path, branded: carriesBrand(c) });
      if (ancestors.includes(c)) continue;
      const chain = [...ancestors, c];
      if (checker.isArrayType(c) || checker.isTupleType(c)) {
        for (const e of checker.getTypeArguments(c as ts.TypeReference)) visit(e, `${path}[]`, chain);
        continue;
      }
      if (info !== undefined) {
        const v = info.type;
        const element = checker.isArrayType(v) ? checker.getTypeArguments(v as ts.TypeReference)[0] : v;
        if (element !== undefined && !parts(element).every((e) => e.flags & PRIMITIVE)) recordValueTypes.add(v);
        visit(v, `${path}.*`, chain);
        continue;
      }
      for (const p of checker.getPropertiesOfType(c)) {
        if ((p.declarations ?? []).includes(brandDecl)) continue;
        visit(checker.getTypeOfSymbol(p), path === "" ? p.name : `${path}.${p.name}`, chain);
      }
    }
  };
  visit(compiledSet, "", []);

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

  return { checker, carriesBrand, carriesUnrecognised, containsBrand, dictionaries, closedFields, recordValueTypes, parts };
}

const WIDE_KEY = ts.TypeFlags.String | ts.TypeFlags.TemplateLiteral | ts.TypeFlags.StringMapping | ts.TypeFlags.Any | ts.TypeFlags.Unknown;
/** The reflective reads and own-membership tests that are the owner's business: `Object.hasOwn`, `Reflect.get`, … */
const REFLECTIVE: Readonly<Record<string, readonly string[]>> = {
  Object: ["hasOwn", "getOwnPropertyDescriptor"],
  Reflect: ["get", "has", "getOwnPropertyDescriptor"],
};
/** The constructors of a plain dictionary that a `NameKeyed` value must not be built with (it is built by `nameKeyed`). */
const OBJECT_CONSTRUCTORS = ["fromEntries", "assign", "create"];

/** `Object.fromEntries` → ["Object", "fromEntries"]; anything else → null. */
const memberCall = (e: ts.Expression): [string, string] | null =>
  ts.isPropertyAccessExpression(e) && ts.isIdentifier(e.expression) ? [e.expression.text, e.name.text] : null;

/** Is this element access READ — anything but the target of a plain `=` (compound assignments read first) or `delete`? */
function isRead(node: ts.ElementAccessExpression): boolean {
  let n: ts.Node = node;
  while (ts.isParenthesizedExpression(n.parent)) n = n.parent;
  const p = n.parent;
  if (ts.isBinaryExpression(p) && p.left === n && p.operatorToken.kind === ts.SyntaxKind.EqualsToken) return false;
  if (ts.isDeleteExpression(p)) return false;
  return true;
}

/** Every read of a name-keyed dictionary in `program`'s files that pass `consider`. Exported for the planted self-test. */
export function findOwnReads(program: ts.Program, consider: (fileName: string) => boolean): OwnRead[] {
  const { checker, carriesBrand, carriesUnrecognised, containsBrand, recordValueTypes, parts } = analyse(program);
  const receiverParts = (e: ts.Expression): readonly ts.Type[] => parts(checker.getNonNullableType(checker.getTypeAtLocation(e)));
  const stringIndexed = (c: ts.Type): boolean =>
    !(checker.isArrayType(c) || checker.isTupleType(c)) && checker.getIndexInfoOfType(c, ts.IndexKind.String) !== undefined;
  const launderedDictionary = (e: ts.Expression): boolean =>
    receiverParts(e).some((c) => {
      if (!stringIndexed(c)) return false;
      return recordValueTypes.has(checker.getIndexInfoOfType(c, ts.IndexKind.String)!.type);
    });
  const wideKey = (e: ts.Expression): boolean =>
    parts(checker.getTypeAtLocation(e)).some((k) => (k.flags & WIDE_KEY) !== 0 || (k.isIntersection() && k.types.some((p) => (p.flags & WIDE_KEY) !== 0)));
  const out: OwnRead[] = [];
  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile || !consider(sf.fileName) || norm(sf.fileName) === norm(OWNER)) continue;
    const record = (node: ts.Node, kind: OwnReadKind): void => {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      out.push({ file: sf.fileName, line: line + 1, kind, text: node.getText(sf).replace(/\s+/g, " ").slice(0, 120) });
    };
    const visit = (node: ts.Node): void => {
      if (ts.isElementAccessExpression(node)) {
        const recv = receiverParts(node.expression);
        if (recv.some((c) => carriesBrand(c))) record(node, "index");
        else if (launderedDictionary(node.expression)) record(node, "laundered-index");
        else if (isRead(node) && wideKey(node.argumentExpression)) {
          if (recv.some((c) => (c.flags & ts.TypeFlags.Any) !== 0)) record(node, "any-index");
          else if (recv.some(stringIndexed)) record(node, "wide-index");
        }
      } else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.InKeyword) {
        if (receiverParts(node.right).some((c) => carriesBrand(c))) record(node, "in");
        else if (wideKey(node.left) && receiverParts(node.right).some(stringIndexed)) record(node, "wide-in");
      } else if (ts.isObjectBindingPattern(node)) {
        if (node.elements.some((el) => !el.dotDotDotToken) && carriesBrand(checker.getTypeAtLocation(node))) record(node, "destructure");
      } else if (
        ts.isBinaryExpression(node) &&
        node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
        ts.isObjectLiteralExpression(node.left)
      ) {
        if (carriesBrand(checker.getTypeAtLocation(node.right))) record(node, "destructure");
      } else if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)) {
        if (!ts.isConstTypeReference(node.type)) {
          const from = checker.getTypeAtLocation(node.expression);
          const to = checker.getTypeAtLocation(node.type);
          if (containsBrand(from)) record(node, "cast");
          else if (carriesUnrecognised(from) && !carriesUnrecognised(to) && !(to.flags & ts.TypeFlags.String)) record(node, "vocabulary-cast");
        }
      } else if (ts.isPropertyAccessExpression(node) && node.name.text === "hasOwnProperty") {
        record(node, "hand-rolled");
      } else if (ts.isCallExpression(node)) {
        const callee = memberCall(node.expression);
        const arg0 = node.arguments[0];
        if (callee !== null && (REFLECTIVE[callee[0]] ?? []).includes(callee[1])) record(node, "hand-rolled");
        else if (callee?.[0] === "JSON" && callee[1] === "parse" && arg0 !== undefined && ts.isCallExpression(arg0)) {
          const inner = memberCall(arg0.expression);
          const x = arg0.arguments[0];
          if (inner?.[0] === "JSON" && inner[1] === "stringify" && x !== undefined && containsBrand(checker.getTypeAtLocation(x))) record(node, "copy");
        } else if (callee?.[0] === "Object" && OBJECT_CONSTRUCTORS.includes(callee[1])) {
          const want = checker.getContextualType(node);
          if (want !== undefined && carriesBrand(want)) record(node, "construct");
        }
      } else if (ts.isObjectLiteralExpression(node)) {
        const want = checker.getContextualType(node);
        if (want !== undefined && carriesBrand(want)) record(node, "construct");
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
      "core/dataset.ts",
      "core/acl-coverage.ts",
      "core/band-qualification.ts",
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
      "fabric3d/FabricLegend.tsx",
      "ui/primitives.tsx",
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

  it("the run-time list withoutPrototypes walks (core/own.ts) is exactly the derived set of compiled dictionaries", () => {
    const derived = [...new Set(analyse(program()).dictionaries.map((d) => d.path))].sort();
    expect([...COMPILED_NAME_KEYED_PATHS].sort()).toEqual(derived);
  }, 60_000);

  /* The compiled fields typed by a closed vocabulary that do NOT carry `Unrecognised`, each with why that is honest.
     Not a list standing in for the class: the class is DERIVED below (every string-literal-typed field of
     CompiledDataset), and every member must be either Unrecognised-carrying or classified here — a new closed field fails
     until it is one or the other. */
  const ENFORCED_AT_COMPILE: Readonly<Record<string, string>> = Object.fromEntries([
    ...["fabric", "aclBindings", "ribEvidence", "producerEmission"].flatMap((doc) => [
      [`${doc}.meta.sourceOrigin`, "the binding label; refused outside SOURCE_ORIGINS (E_SOURCE_LABEL)"],
      [`${doc}.meta.sourceDigestForm`, "the binding label; refused outside DIGEST_FORMS (E_SOURCE_LABEL)"],
    ]),
    ["fabric.findings[].evidenceBasis", "refused outside the engine contract (E_EVIDENCE_CONTRACT)"],
    ["fabric.findings[].evidenceRefs[].kind", "refused outside the engine contract (E_EVIDENCE_CONTRACT)"],
    ["fabric.findings[].evidenceRefs[].role", "refused outside the engine contract (E_EVIDENCE_CONTRACT)"],
    ["fabric.devices[].impact.assessable", "ownedImpact admits only the four persisted owner states; unknown or unreadable verdicts become null and hold all measures (compile-impact-owner.test.ts: unknown verdict)"],
    ["fabric.evidenceRecords[].type", "computed by the compiler from the JSON type, never read from the snapshot"],
  ]);

  it("no compiled field claims a closed vocabulary the compiler does not enforce: each carries Unrecognised, or is refused or computed at compile", () => {
    const { closedFields } = analyse(program());
    expect(closedFields.filter((f) => !f.unrecognised).map((f) => f.path).sort()).toEqual(Object.keys(ENFORCED_AT_COMPILE).sort());
    expect(closedFields.filter((f) => f.unrecognised).map((f) => f.path).sort()).toEqual(
      ["fabric.crossLayer[].severity", "fabric.devices[].band", "fabric.devices[].kind", "fabric.findings[].severity"],
    );
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

  it("is live: a planted module reading a compiled dictionary or a constant table every way it can be read is flagged, and own() is not", () => {
    const planted = join(SRC, "core", "__planted_own_reader.ts").split(sep).join("/");
    /* Line numbers are the array index + 1. The refuter's eleven read shapes are lines 3-13. */
    const lines = [
      `import type { AclLine, Band, Fabric, Finding, NameKeyed, RouteEntry, Severity } from "./types";`, // 1
      `import { nameKeyed, own } from "./own";`, // 2
      `export function r1(f: Fabric, h: string) { return Reflect.get(f.routes, h); }`, // 3
      `function getOf<T>(d: Record<string, T>, k: string) { return d[k]; } export function r2(f: Fabric, h: string) { return getOf(f.routes, h); }`, // 4
      `export function r3(f: Fabric, h: string) { const d: Record<string, readonly RouteEntry[]> = f.routes; return d[h]; }`, // 5
      `export function r4(f: Fabric, h: string) { const d: { [k: string]: unknown } = f.routes; return d[h]; }`, // 6
      `export function r5(f: Fabric, h: string) { const d: any = f.routes; return d[h]; }`, // 7
      `export function r6(f: Fabric, h: string) { return JSON.parse(JSON.stringify(f.routes))[h]; }`, // 8
      `export function r7(f: Fabric, h: string, a: string) { const d: Record<string, AclLine[] | undefined> = f.acls[h] ?? {}; return d[a]; }`, // 9
      `export function r8(f: Fabric, h: string) { return { ...f.routes }[h]; }`, // 10
      `export function r9(f: Fabric, h: string) { return Object.fromEntries(Object.entries(f.routes))[h]; }`, // 11
      `export function r10(f: Fabric, h: string) { return f.routes?.[h]; }`, // 12
      `export function r11(f: Fabric, h: string) { return Object.assign({}, f.routes)[h]; }`, // 13
      `export function a(f: Fabric, h: string) { return h in f.interfaces; }`, // 14
      `export function c(f: Fabric, h: string) { const { [h]: x } = f.acls; return x; }`, // 15
      `export function e(f: Fabric) { return (f.objectGroups as unknown as Record<string, unknown>)["core1"]; }`, // 16
      // A CONSTANT TABLE indexed by a snapshot value (the category, a band): read by a wide key, it must go through own.
      `const FAMILY: Readonly<Record<string, readonly string[]>> = { L1: ["physical"] }; export function t1(x: Finding) { return FAMILY[x.category ?? ""]; }`, // 17
      `export function t2(x: Finding) { return x.category !== null && x.category in FAMILY; }`, // 18
      `export function t3(o: object, k: string) { return Object.prototype.hasOwnProperty.call(o, k) || Object.hasOwn(o, k); }`, // 19
      `export function t4(f: Fabric, h: string) { return structuredClone(f.routes)[h]; }`, // 20
      `export function t5(): NameKeyed<number> { return Object.fromEntries([["a", 1]]); } export const t6: NameKeyed<number> = {};`, // 21
      `const TONE: Readonly<Record<Severity, string>> = { Critical: "c", High: "h", Medium: "m", Low: "l", Info: "i" }; export function t7(x: Finding) { return TONE[x.severity as Severity]; }`, // 22
      `export function t8(x: Finding, d: { band: Band | null }) { return (x.severity as string).length + String(d.band).length; }`, // 23 — to plain string: fine
      // NOT flagged: a dictionary of numbers read by a literal; a Map; the owner; nameKeyed; a closed table by a narrowed key.
      `export function n1(m: Record<string, number>) { return m["a"]; } export function n2(m: Map<string, number>, k: string) { return m.get(k); }`, // 24
      `export function n3(f: Fabric, h: string) { return own(own(f.acls, h), "MGMT_IN") ?? own(FAMILY, h); } export const n4 = nameKeyed([["a", 1]]);`, // 25
      `export function n5(x: Finding) { return x.severity === "High" ? TONE[x.severity] : String(x.severity); }`, // 26
    ];
    const source = lines.join("\n");
    const opts = compilerOptions();
    const host = ts.createCompilerHost(opts);
    const origGet = host.getSourceFile.bind(host);
    host.getSourceFile = (name, lang, onErr, create) =>
      norm(name) === norm(planted) ? ts.createSourceFile(name, source, lang, true, ts.ScriptKind.TS) : origGet(name, lang, onErr, create);
    const origExists = host.fileExists.bind(host);
    host.fileExists = (name) => norm(name) === norm(planted) || origExists(name);
    const p = ts.createProgram([planted, TYPES, OWNER, DATASET_TYPES], opts, host);
    const reads = findOwnReads(p, (f) => norm(f) === norm(planted));
    const kindsAt = (line: number): string[] => [...new Set(reads.filter((r) => r.line === line).map((r) => r.kind))].sort();
    /* Every read shape the refuter planted (3-13), and every constant-table and copy shape (14-22), is flagged; 23-26
       are not. */
    expect([...new Set(reads.map((r) => r.line))].sort((x, y) => x - y)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]);
    expect(kindsAt(3)).toEqual(["hand-rolled"]);
    expect(kindsAt(4)).toContain("wide-index");
    expect(kindsAt(5)).toEqual(["wide-index"]);
    expect(kindsAt(6)).toEqual(["wide-index"]);
    expect(kindsAt(7)).toEqual(["any-index"]);
    expect(kindsAt(8)).toEqual(["any-index", "copy"]);
    expect(kindsAt(12)).toEqual(["index"]);
    expect(kindsAt(16)).toEqual(["cast"]);
    expect(kindsAt(17)).toEqual(["wide-index"]);
    expect(kindsAt(18)).toEqual(["wide-in"]);
    expect(kindsAt(19)).toEqual(["hand-rolled"]);
    expect(kindsAt(20)).toEqual(["index"]);
    expect(kindsAt(21)).toEqual(["construct"]);
    expect(kindsAt(22)).toEqual(["vocabulary-cast"]);
  }, 120_000);
});
