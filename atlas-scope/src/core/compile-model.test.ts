// @vitest-environment node
/**
 * compile-model.test.ts — there is ONE compiler, it is pure, and a browser can run it.
 *
 * WHY. The snapshot is to be compiled at runtime in the browser as well as at build time in Node
 * (one-door integration A.1–A.2). Two compilers — a Node one and a browser port — would drift, and the
 * drift would be invisible: both would produce a plausible model, bound to the same digest, that
 * disagree about the evidence. So the compile logic lives in `tools/lib/compile-model.mjs` (and the
 * validator in `tools/lib/validate-snapshot.mjs`), and the Node CLIs are thin wrappers over them.
 *
 * WHAT THIS PINS:
 *   - the pure modules' whole import graph names no `node:` builtin, no bare package and no Node
 *     global (Buffer, process, require, …) — checked on the TypeScript AST, with a planted violation
 *     proving the checker fires;
 *   - every `.d.mts` beside a tools module declares exactly the names that module exports at runtime,
 *     so the phase-3 loader's types cannot drift from the code it imports;
 *   - the sections the compiler reads are the class `SECTIONS_READ` names — derived from the compiler's
 *     own text, not a hand-kept list — because the validator's section-schema gate iterates over it;
 *   - the pure path (bytes → validate → bind → compileAll → serialise) reproduces all four shipped
 *     files byte-for-byte: the same path a browser will take.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import { compileAll, META_KEYS_READ, OUTPUTS, SECTIONS_READ, serialiseCompiled } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
/* The TRACKED model, read from disk: the cases below compare the tracked files, byte for byte, with a compile of
   the source THEIR meta names. The `../data/fabric.json` import resolves to another dataset under a phase leg's
   override (ATLAS_DATASET_DIR), which paired the tracked bytes with another dataset's source (phase 3.5 close). */
const fabricJson: unknown = JSON.parse(readFileSync(resolve(PKG, "src", "data", "fabric.json"), "utf8"));
const TOOLS = resolve(PKG, "tools");
const LIB = resolve(TOOLS, "lib");
const PURE = ["compile-model.mjs", "validate-snapshot.mjs"].map((f) => resolve(LIB, f));
const posix = (p: string): string => relative(PKG, p).split("\\").join("/");

/** Node-only globals a browser module must not name. */
const NODE_GLOBALS = new Set(["Buffer", "process", "require", "module", "exports", "__dirname", "__filename", "global", "setImmediate"]);

/** The names a module can reach the global object by. */
const GLOBAL_OBJECTS = new Set(["globalThis", "window", "self", "global"]);

/**
 * The purity verdict for one source text: bad import specifiers, and Node globals it names.
 *
 * A Node global is flagged however it is reached: as a bare identifier (`Buffer`), as a member of the
 * global object (`globalThis.process`, `self["require"]` — verifier S1-V7: the first version skipped
 * every property-access NAME, so `globalThis.Buffer` passed), or through a computed member of the global
 * object or a non-literal `import()` — both of which name something this scan cannot see, so they are
 * refused outright rather than trusted.
 */
function impurities(fileName: string, text: string): { specifiers: string[]; globals: string[] } {
  const pre = ts.preProcessFile(text, true, true);
  const specifiers = pre.importedFiles.map((f) => f.fileName);
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.ES2023, true, ts.ScriptKind.JS);
  const globals: string[] = [];
  const at = (node: ts.Node): number => sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
  const onGlobalObject = (e: ts.Expression): boolean => ts.isIdentifier(e) && GLOBAL_OBJECTS.has(e.text);
  const visit = (node: ts.Node): void => {
    if (ts.isIdentifier(node) && NODE_GLOBALS.has(node.text)) {
      const p = node.parent;
      const isMemberName = (ts.isPropertyAccessExpression(p) && p.name === node && !onGlobalObject(p.expression)) || (ts.isPropertyAssignment(p) && p.name === node);
      if (!isMemberName) globals.push(`${node.text}@${at(node)}`);
    }
    if (ts.isElementAccessExpression(node) && onGlobalObject(node.expression)) {
      const k = node.argumentExpression;
      if (!ts.isStringLiteralLike(k)) globals.push(`<computed global member>@${at(node)}`);
      else if (NODE_GLOBALS.has(k.text)) globals.push(`${k.text}@${at(node)}`);
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const arg = node.arguments[0];
      if (arg === undefined || !ts.isStringLiteralLike(arg)) globals.push(`<non-literal import()>@${at(node)}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return { specifiers, globals };
}

/**
 * The one directory OUTSIDE tools/lib a pure module may import from: the engine contract (R3). Only a JSON
 * module, imported with `with { type: "json" }`, may come from there — data with no code and no imports of its
 * own, which Node, Vite and a browser all load the same way. Anything else outside tools/lib is refused.
 */
const CONTRACTS = resolve(PKG, "contracts");
const JSON_IMPORT = /\bimport\s+[A-Za-z_$][\w$]*\s+from\s+["']([^"']+\.json)["']\s+with\s*\{\s*type:\s*["']json["']\s*\}/g;

/** Walk the relative import graph from the pure roots; every edge must stay inside tools/lib (or be the contract JSON). */
function pureGraph(): { files: string[]; data: string[]; bad: string[] } {
  const seen = new Set<string>();
  const data = new Set<string>();
  const bad: string[] = [];
  const queue = [...PURE];
  while (queue.length > 0) {
    const file = queue.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    const text = readFileSync(file, "utf8");
    const { specifiers, globals } = impurities(file, text);
    const jsonImports = new Set([...text.matchAll(JSON_IMPORT)].map((m) => m[1]!));
    for (const g of globals) bad.push(`${posix(file)} names the Node global ${g}`);
    for (const s of specifiers) {
      if (!s.startsWith("./") && !s.startsWith("../")) {
        bad.push(`${posix(file)} imports ${s}`);
        continue;
      }
      const target = resolve(dirname(file), s);
      if (s.endsWith(".json")) {
        if (!target.startsWith(CONTRACTS + sep)) bad.push(`${posix(file)} imports the JSON ${s}, which is not an engine contract under contracts/`);
        else if (!jsonImports.has(s)) bad.push(`${posix(file)} imports ${s} without \`with { type: "json" }\` (a browser and Node load JSON only that way)`);
        else {
          JSON.parse(readFileSync(target, "utf8")); // data, and only data
          data.add(posix(target));
        }
        continue;
      }
      if (!target.startsWith(LIB)) bad.push(`${posix(file)} imports ${s}, outside tools/lib`);
      else queue.push(target);
    }
  }
  return { files: [...seen].map(posix).sort(), data: [...data].sort(), bad };
}

describe("the compiler is pure and browser-safe", () => {
  it("its import graph names no node: builtin, no package and no Node global", () => {
    const { files, data, bad } = pureGraph();
    expect(files, "both pure roots are in the graph").toEqual(expect.arrayContaining(["tools/lib/compile-model.mjs", "tools/lib/validate-snapshot.mjs"]));
    expect(data, "the compiler reads the engine contract (R3), as data").toEqual(["contracts/engine-contract.v1.json"]);
    expect(bad).toEqual([]);
  });

  it("the JSON exception is narrow: a JSON outside contracts/, or one imported without the JSON attribute, is flagged", () => {
    const planted = (text: string): string[] => {
      const specifiers = impurities("planted.mjs", text).specifiers;
      const jsonImports = new Set([...text.matchAll(JSON_IMPORT)].map((m) => m[1]!));
      return specifiers.filter((s) => s.endsWith(".json")).map((s) => {
        const target = resolve(LIB, s);
        return !target.startsWith(CONTRACTS + sep) ? "outside" : jsonImports.has(s) ? "ok" : "no-attribute";
      });
    };
    expect(planted('import c from "../../contracts/engine-contract.v1.json" with { type: "json" };')).toEqual(["ok"]);
    expect(planted('import c from "../../contracts/engine-contract.v1.json";')).toEqual(["no-attribute"]);
    expect(planted('import c from "../../src/data/fabric.json" with { type: "json" };')).toEqual(["outside"]);
  });

  it("the checker is live: it flags a planted builtin import, a bare package and a Node global", () => {
    const planted = impurities("planted.mjs", 'import { readFileSync } from "node:fs";\nimport x from "lodash";\nexport const n = Buffer.from("a");\n');
    expect(planted.specifiers).toEqual(["node:fs", "lodash"]);
    expect(planted.globals).toEqual(["Buffer@3"]);
    expect(impurities("ok.mjs", "export const o = { process: 1 }; o.process;").globals).toEqual([]);
  });

  it("the checker sees a Node global reached THROUGH the global object, and what it cannot see it refuses (S1-V7)", () => {
    const planted = impurities(
      "planted.mjs",
      [
        "export const a = globalThis.process.env;", // 1
        'export const b = globalThis.Buffer.from("a");', // 2
        'export const c = self["require"];', // 3
        "export const d = window.setImmediate;", // 4
        "const k = 'pro' + 'cess';", // 5
        "export const e = globalThis[k];", // 6
        "export const f = await import(k);", // 7
        'export const g = await import("./ok.mjs");', // 8 — a literal specifier is preProcessFile's business
        "export const h = globalThis.crypto;", // 9 — a browser global, allowed
      ].join("\n"),
    );
    expect(planted.globals).toEqual(["process@1", "Buffer@2", "require@3", "setImmediate@4", "<computed global member>@6", "<non-literal import()>@7"]);
  });
});

describe("every tools declaration file matches the module it declares", () => {
  const declarations: string[] = [];
  const walk = (d: string): void => {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      if (statSync(p).isDirectory()) walk(p);
      else if (n.endsWith(".d.mts")) declarations.push(p);
    }
  };
  walk(TOOLS);

  it("declares the pure modules and the Node helpers the tests and the loader import", () => {
    expect(declarations.map(posix).sort()).toEqual(
      expect.arrayContaining(["tools/lib/compile-io.d.mts", "tools/lib/compile-model.d.mts", "tools/lib/validate-snapshot.d.mts", "tools/source-binding.d.mts"]),
    );
  });

  it.each(declarations.map((d) => [posix(d)]))("%s declares exactly the runtime exports", async (rel) => {
    const dts = resolve(PKG, rel);
    const sf = ts.createSourceFile(dts, readFileSync(dts, "utf8"), ts.ScriptTarget.ES2023, true);
    const declared = new Set<string>();
    for (const st of sf.statements) {
      const mods = ts.canHaveModifiers(st) ? ts.getModifiers(st) ?? [] : [];
      if (!mods.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) continue;
      if (ts.isInterfaceDeclaration(st) || ts.isTypeAliasDeclaration(st)) continue; // type-only
      if (ts.isVariableStatement(st)) for (const d of st.declarationList.declarations) declared.add(d.name.getText(sf));
      else if ((ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st)) && st.name) declared.add(st.name.text);
    }
    const mod = (await import(pathToFileURL(dts.replace(/\.d\.mts$/, ".mjs")).href)) as Record<string, unknown>;
    expect([...declared].sort()).toEqual(Object.keys(mod).sort());
  });
});

describe("the sections the compiler reads are derived, not listed", () => {
  const text = readFileSync(resolve(LIB, "compile-model.mjs"), "utf8");

  it("every `snap.<key>` the compiler reads is in SECTIONS_READ or META_KEYS_READ, and every entry is read", () => {
    const read = new Set([...text.matchAll(/\bsnap\??\.([A-Za-z_][A-Za-z0-9_]*)/g)].map((m) => m[1]!));
    expect([...read].sort()).toEqual([...SECTIONS_READ, ...META_KEYS_READ].sort());
  });

  it("the compiler never indexes the snapshot dynamically (which would escape the scan above)", () => {
    expect(text).not.toMatch(/\bsnap\??\.?\[/);
  });
});

describe("the pure path reproduces every shipped file", () => {
  it("bytes -> validate -> bind -> compileAll -> serialise equals the four tracked files, byte for byte", () => {
    const meta = (fabricJson as unknown as { meta: { source: string; sourceOrigin: "repository-file" } }).meta;
    const bytes = readFileSync(resolve(PKG, "..", meta.source));
    const v = assertValidSnapshot(bytes);
    const texts = serialiseCompiled(compileAll(v.snap, bindSource(bytes, { source: meta.source, sourceOrigin: meta.sourceOrigin }), { schemaAssumed: v.schemaAssumed }));
    for (const o of OUTPUTS) {
      expect(Buffer.from(texts[o.key], "utf8").equals(readFileSync(resolve(PKG, o.trackedPath))), o.trackedPath).toBe(true);
    }
  });
});

describe("the rib evidence carries the link each adjacency runs over", () => {
  // rib-completeness.ts checks, per session, that the link it runs over is in the table (E2-V1); an
  // adjacency without its address/interface would degrade every session to 'unknown'. Both keys are
  // always present, null when the producer's record lacks them (never guessed).
  it("every adjacency publishes address and interface, copied from the producer record or null", async () => {
    const { compileRibEvidence } = await import("../../tools/lib/compile-model.mjs");
    const meta = (fabricJson as unknown as { meta: { source: string; sourceOrigin: "repository-file" } }).meta;
    const bytes = readFileSync(resolve(PKG, "..", meta.source));
    const v = assertValidSnapshot(bytes);
    const binding = bindSource(bytes, { source: meta.source, sourceOrigin: meta.sourceOrigin });
    const snap = {
      ...(v.snap as Record<string, unknown>),
      routing_neighbors: {
        h1: {
          ospf: [
            { neighbor: "10.9.0.2", state: "FULL/DR", address: "10.9.0.2", interface: "Po1" },
            { neighbor: "10.9.0.3", state: "FULL/BDR" },
          ],
        },
      },
    };
    const doc = compileRibEvidence(snap, binding) as {
      hosts: Record<string, { adjacencies: Record<string, unknown>[] }>;
    };
    expect(doc.hosts.h1?.adjacencies).toEqual([
      { protocol: "ospf", neighbor: "10.9.0.2", state: "FULL/DR", cite: "routing_neighbors.h1.ospf[0]", address: "10.9.0.2", interface: "Po1" },
      { protocol: "ospf", neighbor: "10.9.0.3", state: "FULL/BDR", cite: "routing_neighbors.h1.ospf[1]", address: null, interface: null },
    ]);
  });
});
