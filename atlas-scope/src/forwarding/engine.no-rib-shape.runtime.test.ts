// @vitest-environment node
/**
 * engine.no-rib-shape.runtime.test.ts — a host whose snapshot routing table is written as NULL (not omitted)
 * is a host with no RIB all the way through the in-app upload path: validator, compiler, coverage and trace
 * (acceptance B3; 2026-10 refuter overturn).
 *
 * engine.no-rib.counterfactual.test.ts withdraws a RIB by deleting its key from the COMPILED fabric — the one
 * spelling of absence the compiler used to recognise. The refuter wrote `routes.core1: null` into the
 * SNAPSHOT instead: the compiler turned it into `routes.core1 = []` with core1 still among the routable
 * hosts, and 57 traces crossing core1 came back "dropped" (30 of them decided) or "denied", none
 * indeterminate. Here the tracked sample, with one gateway's routes set to null, goes through exactly what a
 * file the reader opens goes through — `runCompileRequest` (the worker's code: validator, then the one
 * compiler) and `installDataset` — and the real engine is imported over it. No module is mocked: all four
 * documents are one compile of one snapshot.
 *
 * The subject is resolved by property on the unaltered sample: the observed-Active SVI gateway with a
 * collected RIB holding the most collected ACL lines (ties by name), so a denial at it was possible and is
 * part of what must not happen.
 *
 * The same holds for a table the snapshot DOES write as a list, but in a form the engine cannot read (the
 * 2026-10 wave-1 refuter): every prefix in mask notation ("10.0.10.0 255.255.255.0") compiled to a RIB and
 * 36 traces crossing the host were decided drops claiming "it carries no default route" beside the default
 * the engine could not read; every prefix a NUMBER made the engine throw on import. And a table only PARTLY
 * unreadable — its default route alone in mask notation — kept a decided "no route" with no word of the
 * entry it dropped. Each variant below goes through the same path.
 */
import { readFileSync } from "node:fs";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Flow, Trace } from "../core/types";
import type { DatasetIssue } from "../core/dataset/types";
import type { CompiledDataset } from "../core/dataset/types";
import { runCompileRequest } from "../core/dataset/compile-request";
import { asOpenedFile, compileBytes, SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";
import { formatIpv4, hostAddressIn, parseInterfaceAddress, parsePrefix } from "./ip";

const SAMPLE = new Uint8Array(readFileSync(SAMPLE_SNAPSHOT));

function subjectOf(): string {
  const f = compileBytes(SAMPLE, "sample.json").fabric;
  const lines = (h: string): number => Object.values(f.acls[h] ?? {}).reduce((n, ls) => n + ls.length, 0);
  const hosts = [...new Set(f.l3.filter((r) => r.host !== null && (r.fhrpRole ?? "").toLowerCase() === "active" && f.routes[r.host] !== undefined).map((r) => r.host!))];
  hosts.sort((a, b) => lines(b) - lines(a) || a.localeCompare(b));
  const x = hosts[0];
  if (x === undefined) throw new Error("precondition: the tracked sample has an observed-Active SVI gateway with a collected RIB");
  return x;
}

interface Loaded {
  x: string;
  warnings: DatasetIssue[];
  engine: typeof import("./engine");
  claims: typeof import("../core/claims");
  data: typeof import("../core/data");
  rib: typeof import("./rib-completeness");
}

type RouteRow = Record<string, unknown> & { prefix?: unknown };

/** A dotted subnet mask for a prefix length. */
const dottedMask = (bits: number): string => {
  const m = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return [24, 16, 8, 0].map((sh) => (m >>> sh) & 0xff).join(".");
};
/** "a.b.c.d/len" respelled "a.b.c.d m.m.m.m" — a common producer spelling the engine does not read. */
const maskSpelling = (prefix: unknown): string => {
  const [ip, len] = String(prefix).split("/");
  return `${ip} ${dottedMask(Number(len))}`;
};
/** The one actual /0: a least-specific non-default cannot challenge the default-absence sentence. */
const defaultRoute = (rows: RouteRow[]): number => {
  const defaults = rows.flatMap((row, index) => typeof row.prefix === "string" && parsePrefix(row.prefix)?.bits === 0 ? [index] : []);
  expect(defaults.length, "precondition: the subject has exactly one real /0 default route").toBe(1);
  return defaults[0]!;
};

/** Every variant enters through the actual worker and installer before any real consumer is imported. */
async function install(name: string, snap: Record<string, any>, forge?: (set: CompiledDataset) => void): Promise<Omit<Loaded, "x">> {
  vi.resetModules();
  const bytes = new TextEncoder().encode(JSON.stringify(snap, null, 1));
  const source = `${name}.snapshot.json`;
  const out = await runCompileRequest({ bytes: bytes.slice().buffer, label: { source, sourceOrigin: "external-file" }, expect: null }, globalThis.crypto.subtle);
  if (!out.ok) throw new Error(`the ${name} variant was refused: ${JSON.stringify(out.errors)}`);
  forge?.(out.set);
  (await import("../core/dataset/slot")).installDataset(asOpenedFile(out.set, source));
  return {
    warnings: out.warnings,
    engine: await import("./engine"),
    claims: await import("../core/claims"),
    data: await import("../core/data"),
    rib: await import("./rib-completeness"),
  };
}

/** Compile the sample with exactly the subject's table rewritten, then load its real consumers. */
async function load(name: string, alter: (rows: RouteRow[]) => unknown): Promise<Loaded> {
  const x = subjectOf();
  const snap = JSON.parse(new TextDecoder().decode(SAMPLE)) as { routes: Record<string, unknown> };
  expect(Object.hasOwn(snap.routes, x), `precondition: the sample's routes name ${x}`).toBe(true);
  snap.routes[x] = alter(snap.routes[x] as RouteRow[]);
  return { x, ...await install(name, snap) };
}

let loaded: Loaded;

afterAll(() => {
  vi.resetModules();
});

/** Every suggested flow, and a grid between host addresses in every observed SVI subnet plus an off-fabric address. */
function flows(): Flow[] {
  const { data, engine } = loaded;
  const addrs = new Set<string>(["8.8.8.8"]);
  for (const r of data.fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    for (const off of [10, 50]) {
      const h = a === null ? null : hostAddressIn(a.prefix, off);
      if (h !== null) addrs.add(formatIpv4(h));
    }
  }
  const out: Flow[] = engine.suggestedFlows().map((s) => s.flow);
  for (const s of addrs)
    for (const d of addrs)
      for (const [p, port] of [["tcp", 443], ["tcp", 22], ["udp", 53]] as const) if (s !== d) out.push({ srcIp: s, dstIp: d, protocol: p, dstPort: port, srcPort: null });
  return out;
}

/** Spellings of a table the snapshot holds but the engine cannot read as a RIB at all. */
const NO_RIB: [string, (rows: RouteRow[]) => unknown][] = [
  ["null-rib", () => null],
  ["mask-rib", (rows) => rows.map((r) => ({ ...r, prefix: maskSpelling(r.prefix) }))],
  ["number-rib", (rows) => rows.map((r) => ({ ...r, prefix: 10 }))],
];

for (const [name, alter] of NO_RIB) describe(`B3: a routing table written as ${name} in an opened snapshot is no RIB, through validator, compiler, coverage and trace`, () => {
  beforeAll(async () => {
    loaded = await load(name, alter);
  });

  it("the validator warns where, and the dataset the app reads is the opened one", () => {
    const { x, warnings, data } = loaded;
    expect(data.fabric.meta.source).toBe(`${name}.snapshot.json`);
    expect(warnings.filter((w) => w.code === "W_ROUTES_NOT_USABLE").map((w) => w.path)).toEqual([`/routes/${x}`]);
  });

  it("the compiler gives the host no RIB: absent from routes and from the routable hosts", () => {
    const { x, data } = loaded;
    expect(Object.hasOwn(data.fabric.routes, x), `routes.${x} compiled to ${JSON.stringify(data.fabric.routes[x])}`).toBe(false);
    expect(data.hasRib(x)).toBe(false);
    expect(data.fabric.coverage.routableHosts).not.toContain(x);
    expect(data.fabric.coverage.hostsWithRoutes).toBe(data.fabric.coverage.routableHosts.length);
  });

  it("every trace that crosses the host is indeterminate there, names it unmodelled, and is never decided", () => {
    const { x, engine, claims } = loaded;
    const crossing: Trace[] = flows()
      .map(engine.traceFlow)
      .filter((t) => t.hops.some((h) => h.host === x));
    for (const t of crossing) {
      const where = `${JSON.stringify(t.flow)}: ${t.outcome} :: ${t.claim}`;
      expect(t.outcome, where).toBe("indeterminate");
      expect(t.unmodelledHosts, where).toContain(x);
      expect(claims.isDecidedOutcome(t), where).toBe(false);
      expect(t.hops.find((h) => h.host === x)!.verdict, where).toBe("unmodeled");
      expect(t.claim, where).not.toMatch(new RegExp(`collected RIB \\(routes\\.${x}\\)`));
    }
    expect(crossing.length, "traces crossing the no-RIB host (the case this test is about)").toBeGreaterThan(0);
  });
});

describe("B3: a table whose actual /0 default alone is unreadable keeps its RIB, says what it dropped, and decides no drop", () => {
  let dropped = -1;
  beforeAll(async () => {
    loaded = await load("partial-rib", (rows) => {
      dropped = defaultRoute(rows);
      return rows.map((r, i) => (i === dropped ? { ...r, prefix: maskSpelling(r.prefix) } : r));
    });
  });

  it("the entry is warned at its own path and published under coverage; the host keeps its RIB", () => {
    const { x, warnings, data } = loaded;
    const cite = `routes.${x}[${dropped}]`;
    expect(warnings.filter((w) => w.code === "W_ROUTE_ENTRY_UNREADABLE").map((w) => w.path)).toEqual([`/routes/${x}/${dropped}`]);
    expect(data.fabric.coverage.unreadableRouteEntries).toEqual({ [x]: [cite] });
    expect(data.hasRib(x)).toBe(true);
    expect(data.fabric.coverage.routableHosts).toContain(x);
  });

  it("the table reads as incomplete, citing the dropped entry", () => {
    const { x, rib } = loaded;
    const cite = `routes.${x}[${dropped}]`;
    expect(rib.ribIncompleteness(x).map((r) => r.cite)).toContain(cite);
    expect(rib.ribIncompletenessSentence(x) ?? "").toContain(cite);
  });

  it("every no-route drop at the host is undecided, and its claim names the entry the table could not read", () => {
    const { x, engine, claims } = loaded;
    const cite = `routes.${x}[${dropped}]`;
    const drops = flows()
      .map(engine.traceFlow)
      .filter((t) => t.outcome === "dropped" && t.hops.some((h) => h.host === x && h.verdict === "no-route"));
    for (const t of drops) {
      const where = `${JSON.stringify(t.flow)}: ${t.claim}`;
      expect(claims.isDecidedOutcome(t), where).toBe(false);
      expect(t.claim, where).toContain(cite);
      expect(t.claim, where).not.toContain("it carries no default route");
    }
    expect(drops.length, `required no-route challenge at the host whose ${cite} could not be read`).toBeGreaterThan(0);
  });
});

/** Two retained rows separated by unreadable entries: filtered positions 0/1, ORIGINAL indices 1/3. */
function citeSnapshot(host: string): Record<string, any> {
  const snap = JSON.parse(new TextDecoder().decode(SAMPLE)) as Record<string, any>;
  const routes = snap.routes[subjectOf()] as RouteRow[];
  const template = routes.find((row) => typeof row.prefix === "string" && parsePrefix(row.prefix) !== null);
  expect(template, "precondition: the tracked source provides a readable route template").toBeDefined();
  snap.routes = Object.fromEntries([[host, [null, { ...template!, prefix: "10.252.0.0/16" },
    { prefix: "[NOT OBSERVED]" }, { ...template!, prefix: "10.253.0.0/16" }]]]);
  return snap;
}

describe("B3: the actual cite resolver joins ORIGINAL source indices after compile and install", () => {
  for (const host of ["source-host", "edge.name", "edge/branch~x", "__proto__", "constructor", "edge[1]", "edge[raw].name"]) {
    it(`keeps exact source provenance for ${JSON.stringify(host)}, without a positional fallback`, async () => {
      const { data, warnings } = await install("source-index", citeSnapshot(host));
      const rows = data.routesOf(host);
      expect(rows.map((row) => row.cite)).toEqual([`routes.${host}[1]`, `routes.${host}[3]`]);
      for (const [at, original] of [[0, 1], [1, 3]] as const) {
        const cite = `routes.${host}[${original}]`;
        expect(data.resolveCite(cite)).toBe(rows[at]);
        expect(data.resolveCite(`${cite}.prefix`)).toBe(rows[at]!.prefix);
        expect(data.resolveCite(`${cite}.constructor`)).toBeUndefined();
      }
      for (const original of [0, 2, 4]) expect(data.resolveCite(`routes.${host}[${original}]`)).toBeUndefined();
      for (const original of [0, 1, 2, 3]) {
        expect(data.resolveCite(`routes.${host}.${original}`)).toBeUndefined();
        expect(data.resolveCite(`routes.${host}.${original}.prefix`)).toBeUndefined();
        for (const root of [`routes[${host}]`, `.routes[${host}]`, `[routes][${host}]`]) {
          expect(data.resolveCite(`${root}[${original}]`)).toBeUndefined();
          expect(data.resolveCite(`${root}[${original}].prefix`)).toBeUndefined();
        }
      }
      for (const alias of ["01", "+1", "1.0", "1e0", "-1", "١", "9007199254740993"]) {
        expect(data.resolveCite(`routes.${host}[${alias}]`)).toBeUndefined();
        expect(data.resolveCite(`routes.${host}[${alias}].prefix`)).toBeUndefined();
      }
      const escaped = host.replace(/~/g, "~0").replace(/\//g, "~1");
      expect(warnings.filter((warning) => warning.code === "W_ROUTE_ENTRY_UNREADABLE").map((warning) => warning.path))
        .toEqual([`/routes/${escaped}/0`, `/routes/${escaped}/2`]);
      expect(data.resolveCite(`routes.${host}`)).toBe(rows);
      expect(data.resolveCite("routes")).toBe(data.fabric.routes);
      expect(data.resolveCite("coverage.hostsWithRoutes")).toBe(data.fabric.coverage.hostsWithRoutes);
    });
  }

  it("a forged duplicate route cite is ambiguous even when both rows are otherwise valid", async () => {
    const host = "duplicate-source-cite";
    const { data } = await install("duplicate-source-cite", citeSnapshot(host), (set) => {
      const rows = set.fabric.routes[host]!;
      expect(rows.length).toBe(2);
      rows[1]!.cite = rows[0]!.cite;
    });
    expect(data.routesOf(host).length).toBe(2);
    expect(data.resolveCite(`routes.${host}[1]`)).toBeUndefined();
    expect(data.resolveCite(`routes.${host}[1].prefix`)).toBeUndefined();
    expect(data.resolveCite(`routes.${host}[3]`)).toBeUndefined();
  });

  it("literal parent hosts that also spell a route row or field make both interpretations ambiguous", async () => {
    const snap = citeSnapshot("a");
    const valid = snap.routes.a[1] as RouteRow;
    snap.routes = Object.fromEntries([
      ["a", [valid, { ...valid, prefix: "10.251.0.0/16" }]],
      ["a[0]", [valid]],
      ["a[0].prefix", [valid]],
    ]);
    const { data } = await install("ambiguous-literal-parent", snap);
    expect(data.resolveCite("routes.a")).toBe(data.routesOf("a"));
    expect(data.resolveCite("routes.a[0]")).toBeUndefined();
    expect(data.resolveCite("routes.a[0].prefix")).toBeUndefined();
    expect(data.resolveCite("routes.a[1]")).toBe(data.routesOf("a")[1]);
    expect(data.resolveCite("routes.a[1].prefix")).toBe(data.routesOf("a")[1]!.prefix);
    expect(data.resolveCite("routes.a[0][0]")).toBe(data.routesOf("a[0]")[0]);
    expect(data.resolveCite("routes.a[0].prefix[0]")).toBe(data.routesOf("a[0].prefix")[0]);
  });

  it("nested route-field suffixes read own members only, including an array's own indices", async () => {
    const host = "own-source-fields";
    const { data } = await install("own-source-fields", citeSnapshot(host), (set) => {
      const row = set.fabric.routes[host]![0]!;
      const nested = Object.assign(Object.create({ inherited: "must not be cited" }) as Record<string, unknown>,
        { observed: "retained", values: ["first"] });
      Object.defineProperty(row, "details", { value: nested, enumerable: true });
    });
    expect(data.resolveCite(`routes.${host}[1].details.observed`)).toBe("retained");
    expect(data.resolveCite(`routes.${host}[1].details.inherited`)).toBeUndefined();
    expect(data.resolveCite(`routes.${host}[1].details.values[0]`)).toBe("first");
    expect(data.resolveCite(`routes.${host}[1].details.values[01]`)).toBeUndefined();
    expect(data.resolveCite(`routes.${host}[1].details.values.constructor`)).toBeUndefined();
  });
});
