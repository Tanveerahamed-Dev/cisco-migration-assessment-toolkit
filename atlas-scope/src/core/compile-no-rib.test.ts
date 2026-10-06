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
 * THE RULE. A host has a RIB only when its routes value is a list holding at least one entry whose prefix
 * the ENGINE can read — `usableRoutePrefix` (compile-model.mjs), held equal to the engine's own
 * `parsePrefix` (src/forwarding/ip.ts) below. Every other spelling compiles exactly as the key's absence
 * does, and the validator WARNS — its convention for evidence the model will render as not observed
 * (W_SECTION_ABSENT); a warning never blocks. Each case is the tracked sample altered in exactly one way, so
 * the result is attributable to it.
 *
 * The 2026-10 wave-1 refuter found the first rule ("an entry with a non-empty prefix") too weak: a table in
 * mask notation ("10.0.10.0 255.255.255.0", a common producer spelling), IPv6, free text, a /33, an object
 * or a number all passed it, compiled with `hasRib` true and no warning, and a trace reaching the host
 * took the no-route branch — a decided "dropped" whose claim said "it carries no default route" beside a
 * default the engine could not read. A NUMBER prefix went further: `parsePrefix` called `.trim()` on it at
 * engine module load, so every consumer of the engine threw on import.
 *
 * And a table only PARTLY unreadable kept its readable entries and dropped the rest silently. Each dropped
 * entry is now warned at its own path (W_ROUTE_ENTRY_UNREADABLE) and published under
 * `coverage.unreadableRouteEntries`, which the engine reads as a reason the table is incomplete
 * (rib-completeness.ts), so a "no route" there is never a decided absence.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import { compileAll, usableRoutePrefix } from "../../tools/lib/compile-model.mjs";
import { validateSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { parsePrefix } from "../forwarding/ip";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SAMPLE_TEXT = readFileSync(resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json"), "utf8");
const sample = (): Record<string, any> => JSON.parse(SAMPLE_TEXT) as Record<string, any>;
const enc = (v: unknown): Uint8Array => new TextEncoder().encode(JSON.stringify(v, null, 1));

/** Resolve inside a test: the first host with at least three readable routes, so partial cases retain one. */
let subjectHost: string | null = null;
function subject(): string {
  if (subjectHost !== null) return subjectHost;
  const routes = sample().routes as Record<string, unknown>;
  const host = Object.keys(routes)
    .sort()
    .find((h) => {
      const rows = routes[h];
      return Array.isArray(rows) && rows.length >= 3 && rows.every((row: unknown) => {
        if (row === null || typeof row !== "object" || Array.isArray(row)) return false;
        const prefix = (row as { prefix?: unknown }).prefix;
        return typeof prefix === "string" && parsePrefix(prefix) !== null;
      });
    });
  if (host === undefined) throw new Error("precondition: the tracked sample holds a table with at least three readable routes");
  subjectHost = host;
  return subjectHost;
}

/** Validate and compile, the whole path a caller (CLI or in-app upload) takes. */
function compile(snap: Record<string, any>) {
  const bytes = enc(snap);
  const v = validateSnapshot(bytes);
  expect(v.ok, JSON.stringify(v.errors)).toBe(true);
  const set = compileAll(v.snap!, bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed: v.schemaAssumed });
  return {
    warnings: v.warnings,
    fabric: set.fabric as {
      routes: Record<string, unknown[]>;
      coverage: { routableHosts: string[]; hostsWithRoutes: number; unreadableRouteEntries: Record<string, string[]> };
    },
  };
}

const withSubject = (value: unknown): Record<string, any> => {
  const s = sample();
  s.routes[subject()] = value;
  return s;
};

const ABSENT = (): Record<string, any> => {
  const s = sample();
  delete s.routes[subject()];
  return s;
};

/** A dotted mask for a prefix length — the "a.b.c.d m.m.m.m" spelling a producer may emit. */
const dottedMask = (bits: number): string => {
  const m = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return [24, 16, 8, 0].map((sh) => (m >>> sh) & 0xff).join(".");
};
const asMask = (prefix: unknown): string => {
  const [ip, len] = String(prefix).split("/");
  return `${ip} ${dottedMask(Number(len))}`;
};

/**
 * Prefix spellings the engine cannot read, each as a function of the entry's real prefix. The class is
 * "anything `parsePrefix` refuses", so the list is held to that owner below (every one must be refused by
 * it), not offered as the definition.
 */
const UNREADABLE: [string, (prefix: unknown) => unknown][] = [
  ["mask notation", asMask],
  ["IPv6", () => "2001:db8::/32"],
  ["free text", () => "see attached"],
  ["a /33", (p) => `${String(p).split("/")[0]}/33`],
  ["an object", () => ({ a: 1 })],
  ["a number", () => 10],
  ["a list", (p) => [p]],
  ["a boolean", () => true],
];

const SHAPES: [string, () => Record<string, any>][] = [
  ["null", () => withSubject(null)],
  ["an empty list", () => withSubject([])],
  ['the string "not_collected"', () => withSubject("not_collected")],
  ["an object instead of a list", () => withSubject({ note: "not collected" })],
  [
    "a list whose entries carry no prefix",
    () => withSubject((sample().routes[subject()] as Record<string, unknown>[]).map((r) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== "prefix")))),
  ],
  [
    "a list whose entries' prefix is empty or null",
    () => withSubject((sample().routes[subject()] as Record<string, unknown>[]).map((r, i) => ({ ...r, prefix: i % 2 === 0 ? "" : null }))),
  ],
  ...UNREADABLE.map(([name, spell]): [string, () => Record<string, any>] => [
    `a list whose every prefix is ${name}`,
    () => withSubject((sample().routes[subject()] as Record<string, unknown>[]).map((r) => ({ ...r, prefix: spell(r.prefix) }))),
  ]),
];

describe('B3: every spelling of "no routing table" compiles as the table\'s absence', () => {
  it("positive control: the tracked sample has the subject's RIB, and no routes warning", () => {
    const { warnings, fabric } = compile(sample());
    expect(Object.hasOwn(fabric.routes, subject())).toBe(true);
    expect(fabric.coverage.routableHosts).toContain(subject());
    expect(warnings.filter((w) => w.code === "W_ROUTES_NOT_USABLE")).toEqual([]);
  });

  it("control: deleting the key is absence (the one spelling recognised before)", () => {
    const { fabric } = compile(ABSENT());
    expect(Object.hasOwn(fabric.routes, subject())).toBe(false);
    expect(fabric.coverage.routableHosts).not.toContain(subject());
  });

  for (const [name, make] of SHAPES) {
    it(`${name}: no RIB for the host, the same routes and coverage as the key's absence, and a warning naming where`, () => {
      const { warnings, fabric } = compile(make());
      const absent = compile(ABSENT()).fabric;
      expect(Object.hasOwn(fabric.routes, subject()), `routes.${subject()} compiled to ${JSON.stringify(fabric.routes[subject()])}`).toBe(false);
      expect(fabric.coverage.routableHosts).not.toContain(subject());
      expect(fabric.routes).toEqual(absent.routes);
      expect(fabric.coverage.routableHosts).toEqual(absent.coverage.routableHosts);
      expect(fabric.coverage.hostsWithRoutes).toBe(absent.coverage.hostsWithRoutes);
      const w = warnings.filter((x) => x.code === "W_ROUTES_NOT_USABLE");
      const escaped = subject().replace(/~/g, "~0").replace(/\//g, "~1");
      expect(w.map((x) => x.path)).toEqual([`/routes/${escaped}`]);
      expect(w[0]!.message).toContain(`routes.${subject()}`);
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

  /* A table only PARTLY unreadable keeps its readable entries as its RIB — and says, per entry, what it
     dropped: a warning at the entry's own path, and the entry's cite under coverage.unreadableRouteEntries,
     which the engine reads as a reason the table is incomplete. Used to drop them in silence. */
  for (const [name, spell] of [["no prefix", () => null] as [string, (p: unknown) => unknown], ...UNREADABLE]) {
    it(`a host keeps its RIB when only SOME entries are unreadable (${name}): each dropped entry is warned and published`, () => {
      const s = sample();
      const rs = s.routes[subject()] as Record<string, unknown>[];
      const bad = [0, rs.length - 1];
      s.routes[subject()] = rs.map((r, i) => (bad.includes(i) ? { ...r, prefix: spell(r.prefix) } : r));
      const { warnings, fabric } = compile(s);
      expect(fabric.coverage.routableHosts).toContain(subject());
      expect(fabric.routes[subject()]!.length).toBe(rs.length - bad.length);
      expect(warnings.filter((x) => x.code === "W_ROUTES_NOT_USABLE")).toEqual([]);
      const w = warnings.filter((x) => x.code === "W_ROUTE_ENTRY_UNREADABLE");
      const escaped = subject().replace(/~/g, "~0").replace(/\//g, "~1");
      expect(w.map((x) => x.path)).toEqual(bad.map((i) => `/routes/${escaped}/${i}`));
      for (const [index, warning] of w.entries()) expect(warning.message).toContain(`routes.${subject()}[${bad[index]}]`);
      expect(fabric.coverage.unreadableRouteEntries).toEqual({ [subject()]: bad.map((i) => `routes.${subject()}[${i}]`) });
    });
  }

  it("positive control: the tracked sample publishes no unreadable route entry", () => {
    const { warnings, fabric } = compile(sample());
    expect(fabric.coverage.unreadableRouteEntries).toEqual({});
    expect(warnings.filter((x) => x.code === "W_ROUTE_ENTRY_UNREADABLE")).toEqual([]);
  });
});

describe("B3: unreadable non-record rows retain original input indices and exact host keys", () => {
  it("null, scalar, list and prefixless rows before and between real routes are disclosed at their original indices", () => {
    const s = sample();
    const original = s.routes[subject()] as Record<string, unknown>[];
    const valid = original.find((r) => typeof r.prefix === "string" && parsePrefix(r.prefix) !== null);
    expect(valid, "precondition: a real sample route is readable").toBeDefined();
    s.routes[subject()] = [null, valid!, 42, [], true, {}, valid!, { prefix: "N/A" }];
    const bad = [0, 2, 3, 4, 5, 7];
    const { fabric, warnings } = compile(s);
    expect(fabric.routes[subject()]!.map((row) => (row as { cite: string }).cite)).toEqual([1, 6].map((i) => `routes.${subject()}[${i}]`));
    expect(fabric.coverage.unreadableRouteEntries[subject()]).toEqual(bad.map((i) => `routes.${subject()}[${i}]`));
    const escaped = subject().replace(/~/g, "~0").replace(/\//g, "~1");
    expect(warnings.filter((w) => w.code === "W_ROUTE_ENTRY_UNREADABLE").map((w) => w.path)).toEqual(bad.map((i) => `/routes/${escaped}/${i}`));
  });

  for (const host of ["__proto__", "constructor", "hasOwnProperty", "a/b~c"]) {
    it(`a route dictionary owns the exact hostile key ${JSON.stringify(host)}, with escaped warning pointers`, () => {
      const s = sample();
      const original = s.routes[subject()] as Record<string, unknown>[];
      const valid = original.find((r) => typeof r.prefix === "string" && parsePrefix(r.prefix) !== null);
      expect(valid, "precondition: a real sample route is readable").toBeDefined();
      s.routes = Object.fromEntries([[host, [null, valid!, { prefix: "[NOT OBSERVED]" }]]]);
      const { fabric, warnings } = compile(s);
      const escaped = host.replace(/~/g, "~0").replace(/\//g, "~1");
      expect(Object.hasOwn(fabric.routes, host)).toBe(true);
      expect(fabric.coverage.routableHosts).toEqual([host]);
      expect((fabric.routes[host]![0] as { cite: string }).cite).toBe(`routes.${host}[1]`);
      expect(Object.hasOwn(fabric.coverage.unreadableRouteEntries, host)).toBe(true);
      expect(fabric.coverage.unreadableRouteEntries[host]).toEqual([`routes.${host}[0]`, `routes.${host}[2]`]);
      expect(warnings.filter((w) => w.code === "W_ROUTE_ENTRY_UNREADABLE").map((w) => w.path)).toEqual([`/routes/${escaped}/0`, `/routes/${escaped}/2`]);
    });
  }

  it("the duplicate-key validator still refuses repeated route host names before a table can be admitted", () => {
    const control = '{"schema":"collect_parse_snapshot/1","devices":{},"interfaces":{},"routes":{"a":[{"prefix":"10.0.0.0/8"}]}}';
    expect(validateSnapshot(new TextEncoder().encode(control)).ok).toBe(true);
    const raw = '{"schema":"collect_parse_snapshot/1","devices":{},"interfaces":{},"routes":{"a":[{"prefix":"10.0.0.0/8"}],"a":[{"prefix":"0.0.0.0/0"}]}}';
    const result = validateSnapshot(new TextEncoder().encode(raw));
    expect(result.ok).toBe(false);
    expect(result.errors.some((error) => error.code === "E_DUPLICATE_KEY")).toBe(true);
  });
});

describe("B3: the compiler's usable-prefix rule IS the engine's parsePrefix", () => {
  it("they agree on every prefix in the sample, every unreadable spelling above, and the edge cases of the grammar", () => {
    const corpus: unknown[] = [];
    for (const rs of Object.values(sample().routes as Record<string, unknown>)) {
      for (const r of Array.isArray(rs) ? rs : []) {
        const prefix = (r as { prefix?: unknown }).prefix;
        corpus.push(prefix);
        for (const [, spell] of UNREADABLE) corpus.push(spell(prefix));
      }
    }
    corpus.push(
      "0.0.0.0/0", "255.255.255.255/32", " 10.0.0.0/8 ", "10.0.0.0/08", "010.0.0.0/8", "10.0.0/8", "10.0.0.0.0/8", "256.0.0.0/8",
      "10.0.0.0/", "/8", "10.0.0.0/100", "10.0.0.0/-1", "10.0.0.0 /8", "10.0.0.1/24", "", "-", "N/A", "[NOT OBSERVED]", null, undefined,
      Number.NaN, 0, "10.0.0.0/8\n",
    );
    /* The engine reads what the compiler wrote, which is the trimmed text (val), never the raw value. */
    const engine = (v: unknown): string | null => (typeof v === "string" && parsePrefix(v.trim()) !== null ? v.trim() : null);
    let refusedByEngine = 0;
    for (const v of corpus) {
      expect(usableRoutePrefix(v), JSON.stringify(v)).toBe(engine(v));
      if (engine(v) === null) refusedByEngine += 1;
    }
    for (const [name, spell] of UNREADABLE) expect(engine(spell("10.0.10.0/24")), `${name} must be a spelling the engine refuses`).toBeNull();
    expect(refusedByEngine).toBeGreaterThan(UNREADABLE.length);
  });

  it("parsePrefix refuses a value that is not text instead of throwing (it ran at engine module load)", () => {
    for (const v of [10, null, undefined, { a: 1 }, ["10.0.0.0/8"], true]) {
      expect(() => parsePrefix(v as unknown as string), JSON.stringify(v)).not.toThrow();
      expect(parsePrefix(v as unknown as string), JSON.stringify(v)).toBeNull();
    }
  });
});
