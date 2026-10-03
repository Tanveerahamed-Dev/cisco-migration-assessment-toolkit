// @vitest-environment node
/**
 * compile-no-rib.test.ts — a snapshot that says a host has NO routing table compiles to a host with no
 * RIB, whatever spelling the absence takes (acceptance B3; 2026-10 refuter overturn).
 *
 * WHAT WAS WRONG. The compiler built each table with `arr(rs)…filter(r => r.prefix)` and took
 * `routableHosts` from the keys of the result, so `routes.<host>` written as null, [], "not_collected",
 * an object, or a list of prefix-less entries compiled to `routes.<host> = []` with `hasRib(<host>)`
 * true: counted among "the collected RIBs", and a trace reaching it took the no-route branch — a decided
 * "dropped" — instead of the no-RIB branch, which is indeterminate. Only DELETING the key was recognised
 * as absence. The validator never looked at `routes`, and the in-app upload path runs the same validator
 * and compiler (src/core/dataset/compile-request.ts), so the product accepted the input.
 *
 * THE RULE. A host has a RIB only when its routes value is a list holding at least one entry with a
 * prefix. Every other spelling compiles exactly as the key's absence does, and the validator WARNS — its
 * convention for evidence the model will render as not observed (W_SECTION_ABSENT); a warning never
 * blocks. Each case is the tracked sample altered in exactly one way, so the result is attributable to it.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import { compileAll } from "../../tools/lib/compile-model.mjs";
import { validateSnapshot } from "../../tools/lib/validate-snapshot.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SAMPLE_TEXT = readFileSync(resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json"), "utf8");
const sample = (): Record<string, any> => JSON.parse(SAMPLE_TEXT) as Record<string, any>;
const enc = (v: unknown): Uint8Array => new TextEncoder().encode(JSON.stringify(v, null, 1));

/** The subject: the first host, by name, whose sample table is a non-empty list of prefixed entries. */
const SUBJECT = (() => {
  const routes = sample().routes as Record<string, unknown>;
  const host = Object.keys(routes)
    .sort()
    .find((h) => Array.isArray(routes[h]) && (routes[h] as { prefix?: unknown }[]).some((r) => typeof r.prefix === "string" && r.prefix !== ""));
  if (host === undefined) throw new Error("precondition: the tracked sample holds a non-empty routing table");
  return host;
})();

/** Validate and compile, the whole path a caller (CLI or in-app upload) takes. */
function compile(snap: Record<string, any>) {
  const bytes = enc(snap);
  const v = validateSnapshot(bytes);
  expect(v.ok, JSON.stringify(v.errors)).toBe(true);
  const set = compileAll(v.snap!, bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed: v.schemaAssumed });
  return { warnings: v.warnings, fabric: set.fabric as { routes: Record<string, unknown[]>; coverage: { routableHosts: string[]; hostsWithRoutes: number } } };
}

const withSubject = (value: unknown): Record<string, any> => {
  const s = sample();
  s.routes[SUBJECT] = value;
  return s;
};

const ABSENT = (): Record<string, any> => {
  const s = sample();
  delete s.routes[SUBJECT];
  return s;
};

const SHAPES: [string, () => Record<string, any>][] = [
  ["null", () => withSubject(null)],
  ["an empty list", () => withSubject([])],
  ['the string "not_collected"', () => withSubject("not_collected")],
  ["an object instead of a list", () => withSubject({ note: "not collected" })],
  [
    "a list whose entries carry no prefix",
    () => withSubject((sample().routes[SUBJECT] as Record<string, unknown>[]).map((r) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== "prefix")))),
  ],
  [
    "a list whose entries' prefix is empty or null",
    () => withSubject((sample().routes[SUBJECT] as Record<string, unknown>[]).map((r, i) => ({ ...r, prefix: i % 2 === 0 ? "" : null }))),
  ],
];

describe(`B3: every spelling of "no routing table" compiles as the table's absence (subject ${SUBJECT})`, () => {
  it("positive control: the tracked sample has the subject's RIB, and no routes warning", () => {
    const { warnings, fabric } = compile(sample());
    expect(Object.hasOwn(fabric.routes, SUBJECT)).toBe(true);
    expect(fabric.coverage.routableHosts).toContain(SUBJECT);
    expect(warnings.filter((w) => w.code === "W_ROUTES_NOT_USABLE")).toEqual([]);
  });

  it("control: deleting the key is absence (the one spelling recognised before)", () => {
    const { fabric } = compile(ABSENT());
    expect(Object.hasOwn(fabric.routes, SUBJECT)).toBe(false);
    expect(fabric.coverage.routableHosts).not.toContain(SUBJECT);
  });

  for (const [name, make] of SHAPES) {
    it(`${name}: no RIB for the host, the same routes and coverage as the key's absence, and a warning naming where`, () => {
      const { warnings, fabric } = compile(make());
      const absent = compile(ABSENT()).fabric;
      expect(Object.hasOwn(fabric.routes, SUBJECT), `routes.${SUBJECT} compiled to ${JSON.stringify(fabric.routes[SUBJECT])}`).toBe(false);
      expect(fabric.coverage.routableHosts).not.toContain(SUBJECT);
      expect(fabric.routes).toEqual(absent.routes);
      expect(fabric.coverage.routableHosts).toEqual(absent.coverage.routableHosts);
      expect(fabric.coverage.hostsWithRoutes).toBe(absent.coverage.hostsWithRoutes);
      const w = warnings.filter((x) => x.code === "W_ROUTES_NOT_USABLE");
      expect(w.map((x) => x.path)).toEqual([`/routes/${SUBJECT}`]);
      expect(w[0]!.message).toMatch(new RegExp(`\\b${SUBJECT}\\b`));
      expect(w[0]!.message).toMatch(/no (collected )?routing table/);
    });
  }

  it("a routes section that is not an object is warned once at /routes and leaves no host a RIB", () => {
    const s = sample();
    s.routes = [];
    const { warnings, fabric } = compile(s);
    expect(fabric.coverage.routableHosts).toEqual([]);
    expect(warnings.filter((x) => x.code === "W_ROUTES_NOT_USABLE").map((x) => x.path)).toEqual(["/routes"]);
  });

  it("a host keeps its RIB when only SOME entries lack a prefix (the usable ones are its table)", () => {
    const s = sample();
    const rs = s.routes[SUBJECT] as Record<string, unknown>[];
    s.routes[SUBJECT] = rs.map((r, i) => (i === 0 ? { ...r, prefix: null } : r));
    const { warnings, fabric } = compile(s);
    expect(fabric.coverage.routableHosts).toContain(SUBJECT);
    expect(fabric.routes[SUBJECT]!.length).toBe(rs.length - 1);
    expect(warnings.filter((x) => x.code === "W_ROUTES_NOT_USABLE")).toEqual([]);
  });
});
