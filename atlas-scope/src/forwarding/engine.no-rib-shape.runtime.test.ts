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
 */
import { readFileSync } from "node:fs";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Flow, Trace } from "../core/types";
import type { DatasetIssue } from "../core/dataset/types";
import { runCompileRequest } from "../core/dataset/compile-request";
import { asOpenedFile, compileBytes, SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "./ip";

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
}
let loaded: Loaded;

beforeAll(async () => {
  vi.resetModules();
  const x = subjectOf();
  const snap = JSON.parse(new TextDecoder().decode(SAMPLE)) as { routes: Record<string, unknown> };
  expect(Object.hasOwn(snap.routes, x), `precondition: the sample's routes name ${x}`).toBe(true);
  snap.routes[x] = null;
  const bytes = new TextEncoder().encode(JSON.stringify(snap, null, 1));
  const out = await runCompileRequest({ bytes: bytes.slice().buffer, label: { source: "null-rib.snapshot.json", sourceOrigin: "external-file" }, expect: null }, globalThis.crypto.subtle);
  if (!out.ok) throw new Error(`the null-RIB variant was refused: ${JSON.stringify(out.errors)}`);
  (await import("../core/dataset/slot")).installDataset(asOpenedFile(out.set, "null-rib.snapshot.json"));
  loaded = { x, warnings: out.warnings, engine: await import("./engine"), claims: await import("../core/claims"), data: await import("../core/data") };
});

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

describe("B3: a routing table written as null in an opened snapshot is no RIB, through validator, compiler, coverage and trace", () => {
  it("the validator warns where, and the dataset the app reads is the opened one", () => {
    const { x, warnings, data } = loaded;
    expect(data.fabric.meta.source).toBe("null-rib.snapshot.json");
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
    expect(crossing.length, "traces crossing the null-RIB host (the case this test is about)").toBeGreaterThan(0);
  });
});
