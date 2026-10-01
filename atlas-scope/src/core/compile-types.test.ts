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
 *
 * WHY A REDUCED LITERAL (verifier R3-V2R-4). Type-checking the WHOLE compiled sample — a literal of about a
 * megabyte — took 22.5 s on a quiet host and timed out at 120 s on a busy one: the cost was the literal's size,
 * so the verdict depended on the host. TypeScript checks a literal member by member, so two members of one
 * array with the same shape prove the same thing twice. `representative` keeps, of every array, only the
 * elements that add a type FACT not already presented — an object's keys, a member's type, every enum-like
 * string VALUE (so a literal-union field like `severity` is checked for every value the compiler produced), and
 * each array element's COMBINATION of those facts (TypeScript checks an element whole, so a new combination of
 * already-presented facts is a new fact; verifier P3A1-V2-3). `typeSpace` proves the reduction lossless for this
 * purpose: the set of facts — the keys of every object, the type of every member, every enum-like value, every
 * element's combination — is IDENTICAL for the full sets and the reduced ones. The limits below are the ones this file already carried (none raised); the work under them
 * is what shrank.
 */
import { createHash } from "node:crypto";
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

/* ── the shape-preserving reduction ─────────────────────────────────────────────────────────── */

/** A path with every array index folded, so every element of an array shares one path. */
const fold = (path: string): string => path.replace(/\[\d+\]/g, "[]");
/** A string member whose folded path carries at most this many distinct values is enum-like: its VALUE is its type. */
const ENUM_MAX = 16;

/** Per folded path, the distinct string values seen there (counting stops once past ENUM_MAX). */
function stringValues(root: unknown): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  const walk = (v: unknown, path: string): void => {
    if (typeof v === "string") {
      const set = out.get(fold(path)) ?? new Set<string>();
      if (set.size <= ENUM_MAX) set.add(v);
      out.set(fold(path), set);
    } else if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${path}[${i}]`));
    else if (v !== null && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, `${path}.${k}`);
  };
  walk(root, "");
  return out;
}

/**
 * The type facts a literal presents to the checker: for every node, its folded path and its type — an object's
 * sorted keys, an array (empty or not), a number, a boolean, null, or a string (its value, where the path is
 * enum-like) — and, for every array element, the combination of its facts. `base` is the path of `root` inside the
 * whole set, so enum-likeness is judged over the whole set; `element` says `root` is itself an array element, whose
 * combination is then a fact too.
 */
function typeSpace(root: unknown, enums: Map<string, Set<string>>, base = "", element = false): Set<string> {
  const walk = (v: unknown, path: string, out: Set<string>): void => {
    const f = fold(path);
    if (typeof v === "string") out.add(`${f}|s:${(enums.get(f)?.size ?? 0) <= ENUM_MAX ? v : ""}`);
    else if (Array.isArray(v)) {
      out.add(`${f}|a${v.length === 0 ? ":empty" : ""}`);
      v.forEach((x, i) => {
        /* An element's facts, and their COMBINATION as one fact of its own: TypeScript checks an element against
           the element type whole, so a combination no single fact shows (a discriminated union's member with the
           other member's payload) is a type fact too (verifier P3A1-V2-3). */
        for (const o of elementSpace(x, `${path}[${i}]`)) out.add(o);
      });
    } else if (v !== null && typeof v === "object") {
      out.add(`${f}|o:${Object.keys(v).sort().join(",")}`);
      for (const [k, x] of Object.entries(v)) walk(x, `${path}.${k}`, out);
    } else out.add(`${f}|${v === null ? "null" : typeof v}`);
  };
  /** One array element's facts plus the fact of their combination. */
  const elementSpace = (x: unknown, path: string): Set<string> => {
    const own = new Set<string>();
    walk(x, path, own);
    own.add(`${fold(path)}|joint:${createHash("sha256").update([...own].sort().join("\n")).digest("hex")}`);
    return own;
  };
  if (element) return elementSpace(root, base);
  const out = new Set<string>();
  walk(root, base, out);
  return out;
}

/**
 * Of every array, only the elements that add a type fact the elements kept before them do not already present
 * (a greedy cover, in the compiler's order); objects keep every key. Each kept element is reduced the same way,
 * which keeps its own facts (by the same argument, one level down), so the reduced set presents every fact the
 * full set does. `path` is where `root` sits in the set.
 */
function representative<T>(root: T, enums: Map<string, Set<string>>, path = ""): T {
  const reduce = (v: unknown, at: string): unknown => {
    if (Array.isArray(v)) {
      const covered = new Set<string>();
      const kept: unknown[] = [];
      v.forEach((x, i) => {
        const facts = typeSpace(x, enums, `${at}[${i}]`, true);
        if ([...facts].every((f) => covered.has(f))) return;
        for (const f of facts) covered.add(f);
        kept.push(reduce(x, `${at}[${i}]`));
      });
      return kept;
    }
    if (v !== null && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, reduce(x, `${at}.${k}`)]));
    return v;
  };
  return reduce(root, path) as T;
}

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

/** The same sets, reduced to one element per distinct shape (see "WHY A REDUCED LITERAL"). */
function reducedCases(): { full: Record<string, CompiledSet>; reduced: Record<string, CompiledSet>; enums: Record<string, Map<string, Set<string>>> } {
  const full = cases();
  const enums = Object.fromEntries(Object.entries(full).map(([k, v]) => [k, stringValues(v)]));
  const reduced = Object.fromEntries(Object.entries(full).map(([k, v]) => [k, representative(v, enums[k]!)]));
  return { full, reduced, enums };
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
  it("the reduced literal presents EXACTLY the full sets' type facts, at a fraction of the size", () => {
    const { full, reduced, enums } = reducedCases();
    for (const name of Object.keys(full)) {
      expect([...typeSpace(reduced[name], enums[name]!)].sort(), name).toEqual([...typeSpace(full[name], enums[name]!)].sort());
    }
    const size = (x: unknown): number => JSON.stringify(x).length;
    /* Measured 2026-09-28 (host ~90 % busy): the full sets are ~770 000 characters, the reduced ~303 000, and
       the type check itself fell from 3.2 s to 1.3 s. What remains is dominated by records keyed by DATA (an
       evidence record's members, a host's interfaces), whose distinct key sets are kept as facts. Re-measured
       2026-09-29 once each element's COMBINATION of facts became a fact (P3A1-V2-3): 769 770 full, 337 834
       reduced; the assignability check ran in 1.9 s on a busy host. */
    expect(size(reduced), "the reduction removes the bulk of the literal").toBeLessThan(size(full) / 2);
  });

  it("an element whose COMBINATION of facts is new is kept, though each of its facts is already presented (verifier P3A1-V2-3)", () => {
    /* TypeScript checks each element against the element type as a WHOLE, so a discriminated or correlated union
       rejects a combination ({ kind: "a", v: "s" } where kind "a" carries a number) that no single fact shows.
       A cover of independent (path, type) facts dropped exactly that element. */
    const list = [
      { kind: "a", v: 1 },
      { kind: "b", v: "s" },
      { kind: "a", v: "s" },
    ];
    const enums = stringValues(list);
    const reduced = representative(list, enums);
    expect(reduced, "the third element is a new combination and must be presented").toEqual(list);
    // …and one that repeats a combination already presented is still dropped.
    const again = [...list, { kind: "a", v: "s" }];
    expect(representative(again, stringValues(again))).toEqual(list);
    const same = [{ kind: "a", v: 1 }, { kind: "a", v: 2 }];
    expect(representative(same, stringValues(same)), "a repeated shape is presented once").toHaveLength(1);
  });

  it("every compiled set is assignable to CompiledSet, with no excess or missing key", () => {
    const sets = reducedCases().reduced;
    expect(sets.sample!.fabric.evidenceRecords?.length, "the sample's projected evidence records are in the literal").toBeGreaterThan(0);
    // Not vacuous: the rich case really carries non-null evidence and producer prose.
    const f0 = sets.goldenWithEveryFindingField!.fabric.findings[0]!;
    expect(f0.evidenceRefs?.length).toBe(2);
    expect(f0.severityBasis).not.toBeNull();
    expect(typeCheck(sets)).toEqual([]);
  }, 120_000);

  it("the check is live: a planted extra key, a missing key and a wrong-typed value are each reported", () => {
    const sample = reducedCases().reduced.goldenWithoutEvidence!;
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
