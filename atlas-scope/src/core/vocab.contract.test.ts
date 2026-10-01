// @vitest-environment node
/**
 * vocab.contract.test.ts — the closed vocabularies Atlas Scope recognises are the ENGINE's (ADR 0007 D9).
 *
 * WHAT WAS WRONG. Severity, health band (with the engine's not-measured band) and device kind were hand-mirrored
 * constants in core/types.ts that CITED engine constants (cisco_toolkit/analyze.py `_APP_SEV_RANK`, `_HEALTH_BANDS`,
 * `_KIND_RANK` + "device") the engine contract did not project — so an engine-side change could not reach them, and
 * nothing failed when the two disagreed. The engine now projects all three (analyze.engine_contract_projection;
 * tests/test_engine_contract_vocabularies.py pins each against the producer that writes it), and core/vocab.ts
 * READS them from contracts/engine-contract.v1.json; core/types.ts's recognisers and orders ARE those lists.
 *
 * WHAT THIS PINS.
 *   - The TypeScript unions and the contract agree IN BOTH DIRECTIONS. Each union is reified by a
 *     `Record<Union, true>` literal (TypeScript requires every member and rejects any other key, so `npm run
 *     typecheck` fails when the witness and the union part), and the witness's keys must equal the contract's list.
 *     The unions are ALSO read from core/types.ts by the TypeScript parser and compared with the contract, so the
 *     union-to-contract direction fails inside vitest too, not only under the typecheck gate.
 *   - The recognisers read the contract: their orders are the contract reader's lists (identity, not a copy), and a
 *     perturbed contract perturbs what the reader yields.
 *   - A malformed contract is refused (by this reader AND by the compiler's), never defaulted.
 *   - No app/compiler source outside the reader enumerates a whole vocabulary by hand (a ratchet).
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { CompileError, readEngineContract } from "../../tools/lib/compile-model.mjs";
import {
  BAND_ORDER,
  DEVICE_KINDS,
  NOT_MEASURED_BAND,
  SEVERITY_ORDER,
  notMeasuredBand,
  recognisedBand,
  recognisedKind,
  recognisedSeverity,
  type Band,
  type DeviceKind,
  type NotMeasuredBand,
  type Severity,
} from "./types";
import { ENGINE_VOCABULARIES, readEngineVocabularies } from "./vocab";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CONTRACT_PATH = resolve(PKG, "contracts", "engine-contract.v1.json");
const contractFile = (): Record<string, any> => JSON.parse(readFileSync(CONTRACT_PATH, "utf8")) as Record<string, any>;

/* The unions, reified. Adding a member to a union without adding it here, or a key here the union lacks, is a
   type error; the runtime assertions below then compare these keys with the contract. */
const SEVERITY_UNION: Record<Severity, true> = { Critical: true, High: true, Medium: true, Low: true, Info: true };
const BAND_UNION: Record<Band, true> = { Excellent: true, Good: true, Fair: true, Poor: true, Critical: true };
const NOT_MEASURED_UNION: Record<NotMeasuredBand, true> = { "Insufficient Data": true };
const KIND_UNION: Record<DeviceKind, true> = {
  device: true,
  switch: true,
  router: true,
  firewall: true,
  ap: true,
  phone: true,
  endpoint: true,
  unknown: true,
};
const keys = (r: Record<string, true>): string[] => Object.keys(r).sort();
const sorted = (xs: readonly string[]): string[] => [...xs].sort();

describe("the TypeScript unions and the engine contract agree, in both directions", () => {
  it("severity", () => {
    const c = contractFile();
    expect(keys(SEVERITY_UNION), "union members == contract severities").toEqual(sorted(c.severities as string[]));
  });
  it("health band: the scored bands, and the not-measured band marked apart", () => {
    const hb = contractFile().health_bands as { scored: string[]; not_measured: string };
    expect(keys(BAND_UNION), "Band == contract health_bands.scored").toEqual(sorted(hb.scored));
    expect(keys(NOT_MEASURED_UNION), "NotMeasuredBand == contract health_bands.not_measured").toEqual([hb.not_measured]);
    expect(hb.scored).not.toContain(hb.not_measured);
  });
  it("node kind: the collected kind plus the classifier's kinds", () => {
    const nk = contractFile().node_kinds as { collected: string; classified: string[] };
    expect(keys(KIND_UNION), "DeviceKind == contract node_kinds").toEqual(sorted([nk.collected, ...nk.classified]));
  });
});

/* The witnesses above tie a union to the contract only through `npm run typecheck` (tsc -p tsconfig.json): no vitest
   builds that program, so a member added to a union ALONE passed this whole file (verifier S-VOCAB V4, measured). So
   the unions are also READ here, from core/types.ts's own declarations, by the TypeScript parser: each alias must be
   a plain union of string literals (anything else is refused, never skipped), and its members must equal the
   contract's list — the union-to-contract direction inside the suite, independent of the typecheck gate. */
const TYPES_PATH = resolve(PKG, "src", "core", "types.ts");
function declaredUnion(sourceText: string, alias: string): string[] {
  const sf = ts.createSourceFile("types.ts", sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const decls = sf.statements.filter((s): s is ts.TypeAliasDeclaration => ts.isTypeAliasDeclaration(s) && s.name.text === alias);
  if (decls.length !== 1) throw new Error(`core/types.ts declares ${decls.length} type alias(es) named ${alias}, not exactly one`);
  const node = decls[0]!.type;
  const parts = ts.isUnionTypeNode(node) ? [...node.types] : [node];
  return parts.map((p) => {
    if (ts.isLiteralTypeNode(p) && ts.isStringLiteral(p.literal)) return p.literal.text;
    throw new Error(`core/types.ts ${alias} is not a plain union of string literals (member: ${p.getText(sf)}); extend this reader`);
  });
}

describe("the unions AS DECLARED in core/types.ts equal the contract (read by the parser, no typecheck needed)", () => {
  const declared = (alias: string): string[] => sorted(declaredUnion(readFileSync(TYPES_PATH, "utf8"), alias));
  it("Severity == contract severities", () => {
    expect(declared("Severity")).toEqual(sorted(contractFile().severities as string[]));
  });
  it("Band == contract health_bands.scored, and NotMeasuredBand == health_bands.not_measured", () => {
    const hb = contractFile().health_bands as { scored: string[]; not_measured: string };
    expect(declared("Band")).toEqual(sorted(hb.scored));
    expect(declared("NotMeasuredBand")).toEqual([hb.not_measured]);
  });
  it("DeviceKind == contract node_kinds (collected + classified)", () => {
    const nk = contractFile().node_kinds as { collected: string; classified: string[] };
    expect(declared("DeviceKind")).toEqual(sorted([nk.collected, ...nk.classified]));
  });
  it("the reader is live: it sees an added member, and refuses a union it cannot read", () => {
    expect(declaredUnion('export type Band = "Superb" | "Good";', "Band")).toEqual(["Superb", "Good"]);
    expect(declaredUnion('type NotMeasuredBand = "Insufficient Data";', "NotMeasuredBand")).toEqual(["Insufficient Data"]);
    expect(() => declaredUnion('export type Band = "Good" | string;', "Band")).toThrow(/not a plain union/);
    expect(() => declaredUnion("export type Band = (typeof X)[number];", "Band")).toThrow(/not a plain union/);
    expect(() => declaredUnion('export type Other = "x";', "Band")).toThrow(/0 type alias/);
  });
});

describe("the recognisers read the contract — the orders ARE the reader's lists", () => {
  it("each exported order is the contract reader's list (same array, same order as the engine's rank)", () => {
    const c = contractFile();
    expect(SEVERITY_ORDER).toBe(ENGINE_VOCABULARIES.severities);
    expect([...SEVERITY_ORDER]).toEqual(c.severities);
    expect(BAND_ORDER).toBe(ENGINE_VOCABULARIES.scoredBands);
    expect([...BAND_ORDER]).toEqual(c.health_bands.scored);
    expect(NOT_MEASURED_BAND).toBe(c.health_bands.not_measured);
    expect(DEVICE_KINDS).toBe(ENGINE_VOCABULARIES.nodeKinds);
    expect([...DEVICE_KINDS]).toEqual([c.node_kinds.collected, ...c.node_kinds.classified]);
  });
  it("membership is the contract's: every listed term is recognised, and nothing else is", () => {
    for (const s of SEVERITY_ORDER) expect(recognisedSeverity(s), s).toBe(true);
    for (const b of BAND_ORDER) expect(recognisedBand(b), b).toBe(true);
    for (const k of DEVICE_KINDS) expect(recognisedKind(k), k).toBe(true);
    expect(notMeasuredBand(NOT_MEASURED_BAND)).toBe(true);
    expect(recognisedBand(NOT_MEASURED_BAND), "the not-measured band is never a scored band").toBe(false);
    for (const odd of ["", "critical", "Bogus", "constructor", "toString", null, undefined]) {
      expect(recognisedSeverity(odd)).toBe(false);
      expect(recognisedBand(odd)).toBe(false);
      expect(recognisedKind(odd)).toBe(false);
      expect(notMeasuredBand(odd)).toBe(false);
    }
  });
  it("a perturbed contract perturbs the reader (nothing is hand-listed behind it)", () => {
    const c = contractFile();
    c.severities = ["Grave", "Info"];
    c.health_bands = { scored: ["Fine", "Bad"], not_measured: "Unmeasured" };
    c.node_kinds = { collected: "box", classified: ["thing", "unknown"] };
    expect(readEngineVocabularies(c)).toEqual({
      severities: ["Grave", "Info"],
      scoredBands: ["Fine", "Bad"],
      notMeasuredBand: "Unmeasured",
      nodeKinds: ["box", "thing", "unknown"],
    });
  });
});

describe("a malformed vocabulary is refused by BOTH readers, never defaulted", () => {
  const bends: [string, (c: Record<string, any>) => void][] = [
    ["no severities", (c) => void delete c.severities],
    ["an empty severity list", (c) => void (c.severities = [])],
    ["a repeated severity", (c) => void c.severities.push("High")],
    ["a non-string severity", (c) => void c.severities.push(3)],
    ["no health_bands", (c) => void delete c.health_bands],
    ["no scored bands", (c) => void (c.health_bands.scored = [])],
    ["a not-measured band that is a scored band", (c) => void (c.health_bands.not_measured = "Poor")],
    ["an empty not-measured band", (c) => void (c.health_bands.not_measured = "")],
    ["an unknown health_bands key", (c) => void (c.health_bands.extra = ["x"])],
    ["no node_kinds", (c) => void delete c.node_kinds],
    ["a collected kind that is also classified", (c) => void (c.node_kinds.collected = "switch")],
    ["no classified kinds", (c) => void (c.node_kinds.classified = [])],
    ["an unknown node_kinds key", (c) => void (c.node_kinds.extra = "x")],
  ];
  it.each(bends)("%s", (_why, bend) => {
    const good = contractFile();
    expect(() => readEngineVocabularies(good), "positive control (app reader)").not.toThrow();
    expect(() => readEngineContract(good), "positive control (compiler reader)").not.toThrow();
    const bad = structuredClone(good);
    bend(bad);
    expect(() => readEngineVocabularies(bad)).toThrow(/engine contract/);
    let code = "OK";
    try {
      readEngineContract(bad);
    } catch (e) {
      code = e instanceof CompileError ? e.code : String(e);
    }
    expect(code).toBe("E_ENGINE_CONTRACT");
  });
});

/* ── the class: no source restates a whole vocabulary ─────────────────────────────────────────── */

const SKIP_DIRS = new Set(["node_modules", "dist", "dist-hub", ".local-data", "coverage"]);
function sources(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(e.name)) continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) sources(p, out);
    else if (/\.(ts|tsx|mjs)$/.test(e.name) && !/\.(test|spec)\.[a-z]+$/.test(e.name) && !e.name.endsWith(".d.mts")) out.push(p);
  }
  return out;
}
/** Every array literal (`[ ... ]`, no nesting) whose string members include EVERY term of some vocabulary. */
function completeCopies(text: string, vocabularies: Record<string, readonly string[]>): string[] {
  const hits: string[] = [];
  for (const m of text.matchAll(/\[([^[\]]{0,600})\]/g)) {
    const strs = new Set([...m[1]!.matchAll(/["'`]([^"'`]*)["'`]/g)].map((x) => x[1]!));
    for (const [name, terms] of Object.entries(vocabularies)) {
      if (terms.every((t) => strs.has(t))) hits.push(`${name}@${text.slice(0, m.index).split("\n").length}`);
    }
  }
  return hits;
}
/* Copies in files this cluster does not own, routed to their owner (needsFromOthers). A ratchet keyed by file AND
   count: a new copy anywhere fails, and so does removing one without lowering its entry here. */
const KNOWN_FOREIGN_COPIES: Record<string, number> = {};

describe("no source outside the reader enumerates a whole engine vocabulary", () => {
  const VOCABS = {
    severity: ENGINE_VOCABULARIES.severities,
    band: ENGINE_VOCABULARIES.scoredBands,
    kind: ENGINE_VOCABULARIES.nodeKinds,
  };
  it("the scanner is live: it sees a planted copy in each spelling", () => {
    expect(completeCopies('const A = ["Critical", "High", "Medium", "Low", "Info"];', VOCABS)).toEqual(["severity@1"]);
    expect(completeCopies("const B = ['Excellent','Good','Fair','Poor','Critical'] as const;", VOCABS)).toEqual(["band@1"]);
    expect(completeCopies('x\nnew Set(["device","switch","router","firewall","ap","phone","endpoint","unknown"])', VOCABS)).toEqual(["kind@2"]);
    expect(completeCopies('const C = ["router", "device", "ap"];', VOCABS), "a partial ordering is not a copy").toEqual([]);
  });
  it("app and compiler sources hold no copy beyond the declared foreign ratchet", () => {
    const counts: Record<string, number> = {};
    for (const f of [...sources(join(PKG, "src")), ...sources(join(PKG, "tools"))]) {
      const rel = relative(PKG, f).split("\\").join("/");
      const n = completeCopies(readFileSync(f, "utf8"), VOCABS).length;
      if (n > 0) counts[rel] = n;
    }
    expect(counts).toEqual(KNOWN_FOREIGN_COPIES);
  });
});
