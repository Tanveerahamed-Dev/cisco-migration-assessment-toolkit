/**
 * band-read.guard.test.ts — `band-qualification.ts` is the ONLY module that reads `Device.band`.
 *
 * WHY A PARSER GUARD. B1 failed acceptance twice for one reason. The rule "a favourable band on a
 * device whose score partly measures missing evidence is stated qualified" was first applied by
 * hand on one surface, then moved into `presentBand()` and applied by hand on six — and the surfaces
 * nobody listed (the command palette row, the query row description, the `is:healthy` filter, the
 * queue's band column, and more a grep found) went on stating the raw band. A hand-made list of
 * surfaces is the defect shape; a longer list is the same defect.
 *
 * So the invariant is stated about the CLASS: no expression outside the owner reads the `band`
 * property of the device record. "The device record" is resolved by the TYPE CHECKER, never by a
 * variable name (`d`, `dev`, `device`, `row` …) — name matching is the named-subset shape again. A
 * read is any of: property access `x.band`, optional chaining `x?.band`, element access
 * `x["band"]`, and object destructuring `{ band }` / `{ band: b }` (binding or assignment
 * pattern). A read qualifies when the `band` property it resolves to is DECLARED by `Device` in
 * `src/core/types.ts` — which also catches `Pick<Device, …>`, spreads and unions that carry it.
 *
 * The denominator is every non-test `.ts`/`.tsx` under the globs `vitest.config.ts` collects
 * (`src/**`, minus the `_`-segment scratch class), and those globs are pinned below so the walk
 * cannot quietly shrink. The guard also proves itself live inside the suite: a planted in-memory
 * module reading the band through an unrelated variable name and through destructuring must be
 * flagged.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");
const TYPES = join(SRC, "core", "types.ts");
const OWNER = join(SRC, "core", "band-qualification.ts");

const norm = (p: string): string => resolve(p).split(sep).join("/").toLowerCase();

/** Every authored module vitest's globs sit over: src/**, .ts/.tsx, not a test, no `_` segment. */
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name.startsWith("_")) continue; // vitest.config.ts: "src/**/_*/**", "src/**/_*"
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      walk(p, out);
    } else if ([".ts", ".tsx"].includes(extname(p)) && !/\.test\.tsx?$/.test(p) && !p.endsWith(".d.ts")) {
      out.push(p);
    }
  }
  return out;
}

function compilerOptions(): ts.CompilerOptions {
  const cfg = ts.readConfigFile(join(ROOT, "tsconfig.json"), ts.sys.readFile);
  if (cfg.error) throw new Error(ts.flattenDiagnosticMessageText(cfg.error.messageText, "\n"));
  const parsed = ts.parseJsonConfigFileContent(cfg.config, ts.sys, ROOT);
  return { ...parsed.options, noEmit: true };
}

export interface BandRead {
  file: string;
  line: number;
  text: string;
}

/** Does this type (or any union/intersection constituent) carry the `band` Device declares? */
function carriesDeviceBand(checker: ts.TypeChecker, type: ts.Type, bandDecls: readonly ts.Declaration[]): boolean {
  const parts = type.isUnionOrIntersection() ? type.types : [type];
  for (const t of parts) {
    const apparent = checker.getApparentType(t);
    const prop = checker.getPropertyOfType(apparent, "band");
    if (prop && (prop.declarations ?? []).some((d) => bandDecls.includes(d))) return true;
    if (t !== apparent && apparent.isUnionOrIntersection() && carriesDeviceBand(checker, apparent, bandDecls)) return true;
  }
  return false;
}

/** Does this resolved property symbol trace back to `Device.band`? */
function isDeviceBandSymbol(checker: ts.TypeChecker, sym: ts.Symbol | undefined, bandDecls: readonly ts.Declaration[]): boolean {
  if (!sym) return false;
  const seen = new Set<ts.Symbol>();
  const stack: ts.Symbol[] = [sym];
  while (stack.length) {
    const s = stack.pop()!;
    if (seen.has(s)) continue;
    seen.add(s);
    if ((s.declarations ?? []).some((d) => bandDecls.includes(d))) return true;
    if (s.flags & ts.SymbolFlags.Alias) stack.push(checker.getAliasedSymbol(s));
    // Union/intersection receivers produce a synthetic symbol; its roots are the constituents'.
    for (const r of checker.getRootSymbols(s)) if (r !== s) stack.push(r);
  }
  return false;
}

/**
 * Every read of `Device.band` in `program`'s files that pass `consider`. Exported for the planted
 * self-test below; the guard itself runs it over the real tree.
 */
export function findDeviceBandReads(program: ts.Program, consider: (fileName: string) => boolean): BandRead[] {
  const checker = program.getTypeChecker();
  const typesSf = program.getSourceFiles().find((sf) => norm(sf.fileName) === norm(TYPES));
  if (!typesSf) throw new Error("types.ts is not in the program — the guard cannot resolve Device");
  const memberNamed = (sf: ts.SourceFile, iface: string): ts.Declaration | undefined => {
    let found: ts.Declaration | undefined;
    sf.forEachChild((n) => {
      if (ts.isInterfaceDeclaration(n) && n.name.text === iface) {
        for (const m of n.members) if (m.name && ts.isIdentifier(m.name) && m.name.text === "band") found = m;
      }
    });
    return found;
  };
  const deviceBand = memberNamed(typesSf, "Device");
  if (!deviceBand) throw new Error("Device.band not found in types.ts — the guard has nothing to resolve against");
  /* The owner's `BandPresentation.band` is the same raw value under a second name. Reading it outside
     the owner would launder the unqualified band past this guard, so it counts as a read too. */
  const ownerSf = program.getSourceFiles().find((sf) => norm(sf.fileName) === norm(OWNER));
  const presentationBand = ownerSf ? memberNamed(ownerSf, "BandPresentation") : undefined;
  if (ownerSf && !presentationBand) throw new Error("BandPresentation.band not found in the owner");
  const decl: readonly ts.Declaration[] = presentationBand ? [deviceBand, presentationBand] : [deviceBand];

  const out: BandRead[] = [];
  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile || !consider(sf.fileName)) continue;
    const record = (node: ts.Node): void => {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      out.push({ file: sf.fileName, line: line + 1, text: node.getText(sf).replace(/\s+/g, " ").slice(0, 120) });
    };
    const isBandRead = (receiver: ts.Expression | ts.Node, nameNode: ts.Node | undefined): boolean => {
      if (nameNode && isDeviceBandSymbol(checker, checker.getSymbolAtLocation(nameNode), decl)) return true;
      return carriesDeviceBand(checker, checker.getTypeAtLocation(receiver), decl);
    };
    const visit = (node: ts.Node): void => {
      if (ts.isPropertyAccessExpression(node) && node.name.text === "band") {
        if (isBandRead(node.expression, node.name)) record(node);
      } else if (
        ts.isElementAccessExpression(node) &&
        ts.isStringLiteralLike(node.argumentExpression) &&
        node.argumentExpression.text === "band"
      ) {
        if (isBandRead(node.expression, node.argumentExpression)) record(node);
      } else if (ts.isObjectBindingPattern(node)) {
        for (const el of node.elements) {
          const key = el.propertyName ?? el.name;
          const keyText = ts.isIdentifier(key) || ts.isStringLiteralLike(key) ? key.text : null;
          if (keyText === "band" && !el.dotDotDotToken && carriesDeviceBand(checker, checker.getTypeAtLocation(node), decl)) {
            record(el);
          }
        }
      } else if (
        ts.isBinaryExpression(node) &&
        node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
        ts.isObjectLiteralExpression(node.left)
      ) {
        // Destructuring ASSIGNMENT: `({ band } = device)`.
        const rhs = checker.getTypeAtLocation(node.right);
        for (const p of node.left.properties) {
          const key = ts.isShorthandPropertyAssignment(p) || ts.isPropertyAssignment(p) ? p.name : undefined;
          if (key && ts.isIdentifier(key) && key.text === "band" && carriesDeviceBand(checker, rhs, decl)) record(p);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return out;
}

/* THE TREE'S PROGRAM, BUILT ONCE AND COUNTED (acceptance F2, W6 gate 2026-09-25). The whole-tree check
   was ONE test — build a type-checked program over every authored module, then walk all of them —
   ~3 s on a quiet host and 82-160 s on a saturated clone, where it failed. The program is now built
   once per file (lazily, so a single case run with -t still builds it) and the build is COUNTED, as
   tracked-sources.test.ts counts its own; the walk is split one source file per case. Same
   denominator, same predicate, same verdict. */
let programsBuilt = 0;
let treeProgram: ts.Program | undefined;

describe("Device.band is read only by band-qualification.ts (B1 structural guard)", () => {
  const files = walk(SRC);
  const program = (): ts.Program => {
    if (treeProgram === undefined) {
      programsBuilt += 1;
      treeProgram = ts.createProgram(files, compilerOptions());
    }
    return treeProgram;
  };
  const relOf = (f: string): string => relative(SRC, f).split(sep).join("/");
  const vitestConfig = readFileSync(join(ROOT, "vitest.config.ts"), "utf8");

  it("walks the whole denominator vitest collects over, and that denominator is pinned", () => {
    expect(vitestConfig).toContain(`include: ["src/**/*.test.ts", "src/**/*.test.tsx"]`);
    expect(vitestConfig).toContain(`exclude: [...configDefaults.exclude, "src/**/_*/**", "src/**/_*"]`);
    const rel = files.map((f) => relative(SRC, f).split(sep).join("/"));
    // Every directory that holds a surface is in the walk, and so are the known band readers.
    for (const must of [
      "core/band-qualification.ts",
      "core/query.ts",
      "app/CommandPalette.tsx",
      "app/CoverageBar.tsx",
      "panels/PriorityQueue.tsx",
      "panels/Inspector.tsx",
      "panels/DevicePane.tsx",
      "fabric3d/FabricA11yTree.tsx",
      "fabric3d/FabricLabels.tsx",
      "fabric3d/scene.ts",
      "ui/primitives.tsx",
    ]) {
      expect(rel).toContain(must);
    }
    expect(files.length).toBeGreaterThan(60);
  });

  it("builds the tree's program (once: every per-file case below shares it)", () => {
    expect(program().getSourceFiles().filter((sf) => !sf.isDeclarationFile).length).toBeGreaterThanOrEqual(files.length);
  }, 60_000);

  for (const file of files) {
    const readsIn = (): BandRead[] => findDeviceBandReads(program(), (f) => norm(f) === norm(file));
    if (norm(file) === norm(OWNER)) {
      it(`${relOf(file)} (the owner): reads it, so the resolver resolves on the real tree`, () => {
        expect(readsIn().length).toBeGreaterThan(0);
      });
    } else {
      it(`${relOf(file)}: reads no Device.band`, () => {
        expect(readsIn().map((r) => `${relOf(r.file)}:${r.line}  ${r.text}`)).toEqual([]);
      });
    }
  }

  it("built the tree's program at most once for all of the cases above", () => {
    expect(programsBuilt, "the program was built more than once").toBeLessThanOrEqual(1);
  });

  it("is live: a planted module reading the band under any name, by destructuring, or laundered, is flagged", () => {
    const planted = join(SRC, "core", "__planted_band_reader.ts").split(sep).join("/");
    const source = [
      `import type { Device } from "./types";`,
      `export function a(zq: Device) { return zq.band; }`,
      `export function b({ band }: Device) { return band; }`,
      `export function c(x: Device | undefined) { return x?.band; }`,
      `export function d(y: Device) { return y["band"]; }`,
      `export function e(w: Pick<Device, "band" | "host">) { const { band: renamed } = w; return renamed; }`,
      `export function f(list: readonly Device[]) { let band: unknown; for (const v of list) { ({ band } = v); } return band; }`,
      // NOT the device record: a different type that happens to have a band field.
      `interface Other { band: string }`,
      `export function g(o: Other) { return o.band; }`,
      `import { presentBand } from "./band-qualification";`,
      `export function h(q: Device) { return presentBand(q).band; }`,
    ].join("\n");
    const opts = compilerOptions();
    const host = ts.createCompilerHost(opts);
    const origGet = host.getSourceFile.bind(host);
    host.getSourceFile = (name, lang, onErr, create) =>
      norm(name) === norm(planted)
        ? ts.createSourceFile(name, source, lang, true, ts.ScriptKind.TS)
        : origGet(name, lang, onErr, create);
    const origExists = host.fileExists.bind(host);
    host.fileExists = (name) => norm(name) === norm(planted) || origExists(name);
    const program = ts.createProgram([planted, TYPES, OWNER], opts, host);
    const reads = findDeviceBandReads(program, (f) => norm(f) === norm(planted));
    const lines = reads.map((r) => r.line).sort((p, q) => p - q);
    // Lines 2-7 read Device.band six ways under six unrelated names; line 11 launders it through
    // BandPresentation.band. Line 9 reads an unrelated type's `band` and must NOT be flagged —
    // resolution is by declaration/type, so a coincidental property name is not a read.
    expect(lines).toEqual([2, 3, 4, 5, 6, 7, 11]);
  }, 60_000);
});
