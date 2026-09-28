// @vitest-environment node
/**
 * compile-types.test.ts — the compiler's REAL output is checked against the types it declares.
 *
 * WHAT WAS WRONG (verifier S1-R2V-5). `tools/lib/compile-model.d.mts` states that `compileAll` returns
 * the app's own `CompiledSet` (whose `fabric` is `Fabric` from src/core/types.ts), and every TypeScript
 * consumer — the tests today, the phase-3 browser loader tomorrow — trusts that statement: an import of
 * `compile-model.mjs` resolves to the `.d.mts`, never to the implementation. Nothing checked the
 * implementation against it. `compile-model.test.ts` compared export NAMES only, and the JSDoc-inferred
 * return of the `.mjs` is not assignable to `Fabric` at all (measured: `val()` returns `unknown`, so every
 * string field infers as `{}`) — so the declaration was an unchecked assertion.
 *
 * WHAT THIS PINS. The compiled sets the compiler really produces — from the tracked sample, from the
 * repository's golden (with and without the per-finding evidence contract), and from a row that carries
 * every optional producer field — are written out as object LITERALS and assigned to the declared types in
 * a TypeScript program built with this project's own strict settings. A literal gets TypeScript's excess-
 * property check, so a key the compiler emits that the type does not declare fails, a declared key the
 * compiler does not emit fails, and a value of the wrong type (a number where `string | null` is declared)
 * fails. A planted defect proves the checker is live.
 *
 * WHAT IT DOES NOT PROVE. That every code path of the compiler returns the declared shape for every
 * possible input — only for the inputs compiled here. The static route (annotating compile-model.mjs so
 * tsconfig.scripts.json checks its body) is blocked by `val()`, which returns non-string values unchanged;
 * that is recorded as an open item rather than hidden.
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { bindSource, lfNormalise } from "../../tools/source-binding.mjs";
import { compileAll, type CompiledSet } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO = resolve(PKG, "..");
const SAMPLE_REL = "webapp/sample_data/sample_fleet.snapshot.json";

const EVIDENCE_KEYS = ["evidence_basis", "evidence_refs", "evidence_refs_total"];
const goldenWithoutEvidence = (): Record<string, any> => {
  const s = JSON.parse(readFileSync(resolve(REPO, "tests", "golden", "snapshot.json"), "utf8")) as Record<string, any>;
  s.punchlist = (s.punchlist as Record<string, unknown>[]).map((row) => Object.fromEntries(Object.entries(row).filter(([k]) => !EVIDENCE_KEYS.includes(k))));
  return s;
};

function compileBytes(bytes: Uint8Array, source: string, sourceOrigin: "repository-file" | "external-file"): CompiledSet {
  const v = assertValidSnapshot(bytes);
  return compileAll(v.snap, bindSource(bytes, { source, sourceOrigin }), { schemaAssumed: v.schemaAssumed });
}
const compileSnap = (snap: Record<string, unknown>): CompiledSet => compileBytes(new TextEncoder().encode(JSON.stringify(snap)), "case.json", "external-file");

/** The compiled sets under test: every one a real compiler run. */
function cases(): Record<string, CompiledSet> {
  const sample = compileBytes(lfNormalise(readFileSync(resolve(REPO, SAMPLE_REL))), SAMPLE_REL, "repository-file");
  const base = goldenWithoutEvidence();
  // One row carrying EVERY optional producer field, so no Finding field is checked only as null.
  const rich = goldenWithoutEvidence();
  rich.punchlist[0] = {
    ...rich.punchlist[0],
    severity_basis: "observed querier state",
    evidence_confidence: "evidence confidence NOT published by this snapshot",
    evidence_basis: "record",
    evidence_refs: [
      { kind: "interface", host: "core1", ref: "/interfaces/core1/Gi1~10~11", role: "subject", cite: "core1 Gi1/0/1" },
      { kind: "analysis_row", host: null, ref: "/health_scores/0", role: "derived_from", cite: "health score" },
    ],
  };
  rich.punchlist[0].devices = ["core1"];
  return { sample, goldenWithoutEvidence: compileSnap(base), goldenWithEveryFindingField: compileSnap(rich) };
}

/**
 * Type-check `const <name>: CompiledSet = <literal>;` for each set, in one program built with the
 * project's tsconfig.json compiler options. Returns the diagnostics, flattened to text.
 */
function typeCheck(sets: Record<string, unknown>): string[] {
  const configPath = resolve(PKG, "tsconfig.json");
  const cfg = ts.parseJsonConfigFileContent(ts.readConfigFile(configPath, ts.sys.readFile).config, ts.sys, PKG);
  const options: ts.CompilerOptions = { ...cfg.options, noEmit: true, types: [] };
  const file = join(PKG, "src", "core", "compiled-output-typecheck.virtual.ts");
  const text =
    `import type { CompiledSet } from "../../tools/lib/compile-model.mjs";\n` +
    Object.entries(sets)
      .map(([name, set]) => `export const ${name}: CompiledSet = ${JSON.stringify(set)};\n`)
      .join("");
  const host = ts.createCompilerHost(options, true);
  const norm = (p: string): string => resolve(p).toLowerCase();
  const baseGet = host.getSourceFile.bind(host);
  host.getSourceFile = (name, lang, onError, create) =>
    norm(name) === norm(file) ? ts.createSourceFile(name, text, lang, true) : baseGet(name, lang, onError, create);
  const baseExists = host.fileExists.bind(host);
  host.fileExists = (name) => norm(name) === norm(file) || baseExists(name);
  const baseRead = host.readFile.bind(host);
  host.readFile = (name) => (norm(name) === norm(file) ? text : baseRead(name));
  const program = ts.createProgram({ rootNames: [file], options, host });
  const sf = program.getSourceFile(file);
  expect(sf, "the virtual check file is in the program").toBeDefined();
  const diags = [...program.getSyntacticDiagnostics(sf), ...program.getSemanticDiagnostics(sf)];
  // The declarations it leans on must themselves be sound, or a broken .d.mts could pass as "no errors".
  const dts = program.getSourceFile(resolve(PKG, "tools", "lib", "compile-model.d.mts"));
  expect(dts, "the check resolved compile-model.mjs to its declaration").toBeDefined();
  diags.push(...program.getSemanticDiagnostics(dts));
  return diags.map((d) => {
    const where = d.file && d.start !== undefined ? d.file.getLineAndCharacterOfPosition(d.start) : null;
    return `${where ? `${d.file!.fileName.split(/[\\/]/).pop()}:${where.line + 1}:${where.character + 1} ` : ""}TS${d.code}: ${ts.flattenDiagnosticMessageText(d.messageText, "\n").slice(0, 400)}`;
  });
}

describe("the compiler's real output is the shape its declaration states (S1-R2V-5)", () => {
  it("every compiled set is assignable to CompiledSet, with no excess or missing key", () => {
    const sets = cases();
    // Not vacuous: the rich case really carries non-null evidence and producer prose.
    const f0 = sets.goldenWithEveryFindingField!.fabric.findings[0]!;
    expect(f0.evidenceRefs?.length).toBe(2);
    expect(f0.severityBasis).not.toBeNull();
    expect(typeCheck(sets)).toEqual([]);
  }, 120_000);

  it("the check is live: a planted extra key, a missing key and a wrong-typed value are each reported", () => {
    const sample = cases().goldenWithoutEvidence!;
    const extra = structuredClone(sample) as unknown as Record<string, any>;
    extra.fabric.devices[0].aNewUndeclaredField = 1;
    const missing = structuredClone(sample) as unknown as Record<string, any>;
    delete missing.aclBindings.hosts[Object.keys(missing.aclBindings.hosts)[0]!][0].runConfigObserved;
    const wrong = structuredClone(sample) as unknown as Record<string, any>;
    wrong.fabric.findings[0].title = 7;
    const diags = typeCheck({ extra, missing, wrong });
    expect(diags.some((d) => /aNewUndeclaredField/.test(d)), diags.join("\n")).toBe(true);
    expect(diags.some((d) => /runConfigObserved/.test(d)), diags.join("\n")).toBe(true);
    expect(diags.some((d) => /number.*not assignable to type 'string'/s.test(d)), diags.join("\n")).toBe(true);
  }, 120_000);
});
