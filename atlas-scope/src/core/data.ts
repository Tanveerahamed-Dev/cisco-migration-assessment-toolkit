/**
 * data.ts — the compiled evidence model and the indexes every surface reads from.
 *
 * The model is the fabric document of the ONE dataset this page shows, read from `core/dataset.ts`
 * (the only door the compiled documents enter by). In a standalone build that is the bundled sample,
 * statically imported there, so the whole model is available synchronously on first paint: no loading
 * spinner sits between a user and their evidence, and the INP budget never pays for a fetch. When a
 * snapshot was fetched from AssessHub or opened by the reader, it was compiled and installed before
 * the application loaded, and this module reads that one instead — its exported API is the same either
 * way, so none of the modules that import it know or care which.
 */
import { fabricDocument } from "./dataset";
import { holds, own } from "./own";
import type {
  AclLine,
  CrossLayerFinding,
  Device,
  Endpoint,
  Fabric,
  Finding,
  InterfaceRecord,
  L3Interface,
  Link,
  NameKeyed,
  PhysicalHealth,
  ProtocolHealth,
  RouteEntry,
  Severity,
} from "./types";
import { SEVERITY_ORDER } from "./types";

export const fabric: Fabric = fabricDocument;

/* ── primary indexes ───────────────────────────────────────────────────────── */

export const deviceById: ReadonlyMap<string, Device> = new Map(fabric.devices.map((d) => [d.id, d]));
export const linkById: ReadonlyMap<string, Link> = new Map(fabric.links.map((l) => [l.id, l]));
export const findingById: ReadonlyMap<string, Finding> = new Map(fabric.findings.map((f) => [f.id, f]));

/** host -> links touching it (either end). */
export const linksByHost: ReadonlyMap<string, Link[]> = (() => {
  const m = new Map<string, Link[]>();
  for (const l of fabric.links) {
    for (const h of [l.a, l.b]) {
      const list = m.get(h);
      if (list) list.push(l);
      else m.set(h, [l]);
    }
  }
  return m;
})();

/** host -> adjacent hosts. */
export const neighborsByHost: ReadonlyMap<string, string[]> = (() => {
  const m = new Map<string, Set<string>>();
  for (const l of fabric.links) {
    if (!m.has(l.a)) m.set(l.a, new Set());
    if (!m.has(l.b)) m.set(l.b, new Set());
    m.get(l.a)!.add(l.b);
    m.get(l.b)!.add(l.a);
  }
  return new Map([...m].map(([k, v]) => [k, [...v].sort()]));
})();

const groupBy = <T>(items: readonly T[], key: (t: T) => string | null): ReadonlyMap<string, T[]> => {
  const m = new Map<string, T[]>();
  for (const it of items) {
    const k = key(it);
    if (k === null) continue;
    const list = m.get(k);
    if (list) list.push(it);
    else m.set(k, [it]);
  }
  return m;
};

export const findingsByHost: ReadonlyMap<string, Finding[]> = (() => {
  const m = new Map<string, Finding[]>();
  for (const f of fabric.findings) {
    for (const h of f.devices) {
      const list = m.get(h);
      if (list) list.push(f);
      else m.set(h, [f]);
    }
  }
  return m;
})();

export const crossLayerByHost: ReadonlyMap<string, CrossLayerFinding[]> = (() => {
  const m = new Map<string, CrossLayerFinding[]>();
  for (const c of fabric.crossLayer) {
    for (const h of c.hosts) {
      const list = m.get(h);
      if (list) list.push(c);
      else m.set(h, [c]);
    }
  }
  return m;
})();

export const physicalByHost: ReadonlyMap<string, PhysicalHealth[]> = groupBy(fabric.physical, (p) => p.host);
export const protocolsByHost: ReadonlyMap<string, ProtocolHealth[]> = groupBy(fabric.protocols, (p) => p.host);
export const endpointsByHost: ReadonlyMap<string, Endpoint[]> = groupBy(fabric.endpoints, (e) => e.host);
export const l3ByHost: ReadonlyMap<string, L3Interface[]> = groupBy(fabric.l3, (r) => r.host);

/* Each reads the host's OWN entry (core/own.ts): a host the dictionary does not hold — whatever it is named — has
   none, and these three flatten "none collected" into an empty table. A surface that must tell the two apart
   asks `hasRib`, or reads the dictionary through `own`, which answers undefined. */
export const interfacesOf = (host: string): InterfaceRecord[] => own(fabric.interfaces, host) ?? [];
export const routesOf = (host: string): RouteEntry[] => own(fabric.routes, host) ?? [];
export const aclsOf = (host: string): NameKeyed<AclLine[]> => own(fabric.acls, host) ?? {};

/** True only when we actually hold a RIB for this host. Drives every forwarding scope statement. */
export const hasRib = (host: string): boolean => holds(fabric.routes, host);

/* ── ordering helpers shared by every list surface ─────────────────────────── */

/* A Map: the severity asked about is the SNAPSHOT's, and `SEV_RANK[s]` on a plain object ranked a severity named
   "toString" as a function (core/own.ts says why). */
const SEV_RANK: ReadonlyMap<string, number> = new Map(SEVERITY_ORDER.map((s, i) => [s, i]));
export const severityRank = (s: string | null): number => (s === null ? 99 : (SEV_RANK.get(s) ?? 98));

export const bySeverityThenRank = (a: Finding, b: Finding): number =>
  severityRank(a.severity) - severityRank(b.severity) ||
  (a.priority ?? 1e9) - (b.priority ?? 1e9) ||
  (a.rank ?? 1e9) - (b.rank ?? 1e9) ||
  a.id.localeCompare(b.id);

export const severityCounts = (items: readonly { severity: Severity | string }[]): NameKeyed<number> => {
  /* Keyed by a severity the SNAPSHOT supplies, so counted in a Map (tools/lib/compile-model.mjs, THE DICTIONARY
     RULE): on a plain object a severity named "constructor" started its count from the Object function, and one
     named "__proto__" from Object.prototype. Object.fromEntries defines each count as an ordinary member. */
  const counts = new Map<string, number>(SEVERITY_ORDER.map((s) => [s, 0]));
  for (const it of items) counts.set(it.severity, (counts.get(it.severity) ?? 0) + 1);
  return Object.fromEntries(counts);
};

/* ── resolving a citation back to the raw evidence it names ────────────────── */

/**
 * Resolve a `cite` path against the compiled model so the Inspector can show the exact record a
 * claim rests on. Supports `a.b[0]`, `a.b[host=core1]` and plain dotted paths. Returns `undefined`
 * when the path does not resolve — the Inspector renders that as a broken-provenance warning
 * rather than an empty panel, because a claim whose evidence cannot be found is a defect.
 */
export function resolveCite(path: string): unknown {
  const parts = path.split(/[.[]/).map((p) => p.replace(/]$/, "")).filter(Boolean);
  /* A cite's parts are snapshot names (`routes.<host>[0]`), so each step reads an OWN member only (core/own.ts):
     `routes.__proto__`, for a host the dictionary does not hold, resolved to Object.prototype — and a host so
     named then rendered, wherever prose mentioned it, as a citation of that. */
  let cur: unknown = fabric;
  for (const part of parts) {
    if (cur === null || cur === undefined) return undefined;
    const kv = /^([A-Za-z_][\w]*)=(.*)$/.exec(part);
    if (kv && Array.isArray(cur)) {
      const [, key, want] = kv;
      cur = (cur as Record<string, unknown>[]).find((r) => String(own(r, key!)) === want);
      continue;
    }
    if (Array.isArray(cur)) {
      const i = Number(part);
      cur = Number.isInteger(i) ? cur[i] : undefined;
      continue;
    }
    if (typeof cur === "object") {
      cur = own(cur as Record<string, unknown>, part);
      continue;
    }
    return undefined;
  }
  return cur;
}
