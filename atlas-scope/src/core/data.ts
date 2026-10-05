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
import { holds, nameKeyed, own } from "./own";
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
/* The empty table is one of `nameKeyed`'s (core/own.ts): no prototype, so no read of it can answer an inherited member. */
const NO_ACLS: NameKeyed<AclLine[]> = Object.freeze(nameKeyed<AclLine[]>());
export const aclsOf = (host: string): NameKeyed<AclLine[]> => own(fabric.acls, host) ?? NO_ACLS;

/** True only when we actually hold a RIB for this host. Drives every forwarding scope statement. */
export const hasRib = (host: string): boolean => holds(fabric.routes, host);

/* ── ordering helpers shared by every list surface ─────────────────────────── */

/* A Map: the severity asked about is the SNAPSHOT's, and `SEV_RANK[s]` on a plain object ranked a severity named
   "toString" as a function (core/own.ts says why). */
const SEV_RANK: ReadonlyMap<string, number> = new Map(SEVERITY_ORDER.map((s, i) => [s, i]));
/**
 * WHERE A SEVERITY OFF THE GRADED SCALE SORTS — a deliberate position, stated once. The five graded severities rank
 * 0-4, Critical first. A severity the vocabulary does not name, and a record that states none, are NOT points on that
 * scale: ranking an unrecognised "Bogus" 98 — after Info — said it was the least severe finding there is (2026-10-01
 * refuter). So both come AFTER every graded finding in the ranked order — unrecognised first (the producer graded it,
 * in words Atlas Scope does not know), then not stated (it graded nothing) — each shown under its own labelled group
 * (core/query.ts `groupItems`), never folded into a graded one. A sort the reader can REVERSE reads
 * `gradedSeverityRank`, which answers null for both, so they sink in either direction exactly as an unobserved value
 * does (core/query.ts `cmpCell`): an ungraded record is never presented as the extreme of the scale, at either end.
 */
export const UNRECOGNISED_SEVERITY_RANK = SEVERITY_ORDER.length;
export const NOT_STATED_SEVERITY_RANK = SEVERITY_ORDER.length + 1;
export const severityRank = (s: string | null): number => (s === null ? NOT_STATED_SEVERITY_RANK : (SEV_RANK.get(s) ?? UNRECOGNISED_SEVERITY_RANK));
/** The rank on the graded scale, or null for a severity that is not a point on it (unrecognised, or not stated). */
export const gradedSeverityRank = (s: string | null): number | null => (s === null ? null : (SEV_RANK.get(s) ?? null));

export const bySeverityThenRank = (a: Finding, b: Finding): number =>
  severityRank(a.severity) - severityRank(b.severity) ||
  (a.priority ?? 1e9) - (b.priority ?? 1e9) ||
  (a.rank ?? 1e9) - (b.rank ?? 1e9) ||
  a.id.localeCompare(b.id);

/** Counts by the severity each record STATES (a record that states none is not counted here — `tallySeverities` is
 *  the accounting that sums to its input). */
export const severityCounts = (items: readonly { severity: Severity | string | null }[]): NameKeyed<number> => {
  /* Keyed by a severity the SNAPSHOT supplies, so counted in a Map (tools/lib/compile-model.mjs, THE DICTIONARY
     RULE): on a plain object a severity named "constructor" started its count from the Object function, and one
     named "__proto__" from Object.prototype. `nameKeyed` defines each count as an own member of a dictionary with no
     prototype (core/own.ts). */
  const counts = new Map<string, number>(SEVERITY_ORDER.map((s) => [s, 0]));
  for (const it of items) if (it.severity !== null) counts.set(it.severity, (counts.get(it.severity) ?? 0) + 1);
  return nameKeyed(counts);
};

/** A severity tally that accounts for every record it is given: graded + unrecognised + not stated = total. */
export interface SeverityTally {
  /** Every graded severity in SEVERITY_ORDER, zero included ("Info 0" is a statement about a search). */
  graded: { severity: Severity; n: number }[];
  /** Each severity the vocabulary does not name, as the producer wrote it, with its count (ordered by that text). */
  unrecognised: { value: string; n: number }[];
  /** Records that state no severity. */
  notStated: number;
  total: number;
}
/**
 * THE ONE SEVERITY TALLY a surface prints. A tally over the five graded severities alone read `C0 H0 M0 L0 I0` above a
 * list of findings whose severity the vocabulary does not name (2026-10-01 refuter): an all-zero readout over a
 * non-empty list, the false-health class. This one places every record — graded, unrecognised or not stated — so
 * its parts always sum to `total`, which is the input's length.
 */
export function tallySeverities(items: readonly { severity: Severity | string | null }[]): SeverityTally {
  const graded = new Map<string, number>(SEVERITY_ORDER.map((s) => [s, 0]));
  const other = new Map<string, number>();
  let notStated = 0;
  for (const it of items) {
    const s = it.severity;
    if (s === null) notStated++;
    else if (graded.has(s)) graded.set(s, (graded.get(s) ?? 0) + 1);
    else other.set(s, (other.get(s) ?? 0) + 1);
  }
  return {
    graded: SEVERITY_ORDER.map((severity) => ({ severity, n: graded.get(severity) ?? 0 })),
    unrecognised: [...other].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([value, n]) => ({ value, n })),
    notStated,
    total: items.length,
  };
}

/* ── resolving a citation back to the raw evidence it names ────────────────── */

/* A route's cite names its ORIGINAL snapshot index, not its position in the filtered compiled array.
   Keep an exact index once at load; even identical duplicate cites are ambiguous, never first-wins. */
const ROUTE_BY_CITE: ReadonlyMap<string, RouteEntry | null> = (() => {
  const rows = new Map<string, RouteEntry | null>();
  for (const host of Object.keys(fabric.routes)) {
    for (const row of own(fabric.routes, host) ?? []) {
      if (row === null || typeof row !== "object" || typeof row.cite !== "string"
          || !/^routes\..+\[(?:0|[1-9][0-9]*)\]$/.test(row.cite)) continue;
      rows.set(row.cite, rows.has(row.cite) ? null : row);
    }
  }
  return rows;
})();

const citeParts = (path: string): string[] => path.split(/[.[]/).map((p) => p.replace(/]$/, "")).filter(Boolean);

/** Walk field suffixes through OWN members, retaining the generic resolver's non-route semantics. */
function walkCite(cur: unknown, parts: readonly string[], canonicalIndices = false): unknown {
  for (const part of parts) {
    if (cur === null || cur === undefined) return undefined;
    const kv = /^([A-Za-z_][\w]*)=(.*)$/.exec(part);
    if (kv && Array.isArray(cur)) {
      const [, key, want] = kv;
      cur = (cur as Record<string, unknown>[]).find((r) => String(own(r, key!)) === want);
      continue;
    }
    if (Array.isArray(cur)) {
      if (canonicalIndices) {
        if (!/^(?:0|[1-9][0-9]*)$/.test(part)) return undefined;
        cur = own(cur as unknown as Record<string, unknown>, part);
        continue;
      }
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

/**
 * Resolve a `cite` path against the compiled model so the Inspector can show the exact record a
 * claim rests on. Supports `a.b[0]`, `a.b[host=core1]` and plain dotted paths. Returns `undefined`
 * when the path does not resolve — the Inspector renders that as a broken-provenance warning
 * rather than an empty panel, because a claim whose evidence cannot be found is a defect.
 */
export function resolveCite(path: string): unknown {
  if (path.startsWith("routes.")) {
    const parent = own(fabric.routes, path.slice("routes.".length));
    const exact = ROUTE_BY_CITE.get(path);
    if (ROUTE_BY_CITE.has(path)) return parent === undefined && exact !== null && exact?.cite === path ? exact : undefined;
    /* A host may literally contain dots, slashes, brackets or reserved names. Identify it against the
       owned dictionary before tokenising a field suffix; no name is normalised into another subject.
       More than one plausible host/row boundary is ambiguous and therefore resolves nothing. */
    const matches: { cite: string; fields: string }[] = [];
    for (let at = path.indexOf("[", "routes.".length); at >= 0; at = path.indexOf("[", at + 1)) {
      const host = path.slice("routes.".length, at);
      if (!holds(fabric.routes, host)) continue;
      const index = /^\[(0|[1-9][0-9]*)\](?=$|\.)/.exec(path.slice(at));
      if (index !== null) matches.push({ cite: path.slice(0, at + index[0].length), fields: path.slice(at + index[0].length) });
    }
    if (matches.length > 0) {
      if (parent !== undefined || matches.length !== 1) return undefined;
      const match = matches[0]!;
      const row = ROUTE_BY_CITE.get(match.cite);
      if (row === null || row === undefined || row.cite !== match.cite) return undefined;
      return walkCite(row, citeParts(match.fields), true);
    }
    if (parent !== undefined) return parent;
    // No unmatched route spelling may fall through to generic array-position resolution.
    return undefined;
  }
  /* A cite's parts are snapshot names (`routes.<host>[0]`), so each step reads an OWN member only (core/own.ts):
     `routes.__proto__`, for a host the dictionary does not hold, resolved to Object.prototype — and a host so
     named then rendered, wherever prose mentioned it, as a citation of that. */
  return walkCite(fabric, citeParts(path));
}
