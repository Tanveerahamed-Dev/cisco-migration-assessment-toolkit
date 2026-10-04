/**
 * query.ts — the structured-search engine behind the command palette, the finding queue and every
 * dense list.
 *
 * Four properties drive the whole design:
 *
 *  1. A filter answers with three states, not two. `yes` / `no` / `unknown`. `unknown` means the
 *     evidence to decide was never collected, and an `unknown` row is NEVER admitted to a result
 *     set — not by a positive clause, and not by its negation either. `-is:bridge` returns the
 *     devices the engine determined are not bridges, never the ones whose centrality it never
 *     computed. This is the same rule `types.ts` states for `null`, carried into set logic.
 *
 *  2. A clause that cannot be evaluated fails closed and says why. An unrecognised key, a value
 *     naming a field this entity does not carry, or an unknown `is:` predicate returns an EMPTY
 *     result with a stated reason, never the full unfiltered list. A filter that silently does
 *     nothing is a lie about the data: the user reads the whole fleet as "everything matched my
 *     filter". The reason names the VALUE where the value is the question (`has:`, `is:`) — a
 *     schema mismatch and a collection gap are different facts and must not be reported alike.
 *
 *  3. Every result carries its own accounting. For each clause: how many rows it matched, how many
 *     it definitively excluded, how many it could not decide, and what the result would be without
 *     it. Result-level totals partition the same three ways, so `excludedTotal` can never restate
 *     an undecided row as a decided-against one.
 *
 *  4. Every result states the evidence it could NOT have. A row set derived from collected evidence
 *     (findings, cross-layer records) can say nothing whatever about a device the collector never
 *     reached: those devices produce no rows, so filtering to them yields an empty list that means
 *     "nothing was collected", not "nothing was found". Each clause that selects devices reports
 *     which of them are uncollected, with citations, and the result carries the fleet-level version
 *     of the same caveat. This is scope, not a row property — no per-row tri-state can express it.
 *
 * Determinism: no clock, no randomness, no locale-sensitive comparison. Every comparator is a
 * TOTAL order ending in an identity field, so nothing rests on Array.sort stability and results do
 * not shift between JS engines or between calls.
 */
import {
  BAND_GROUP_ORDER,
  BAND_KEY_ORDER,
  bandDegraded,
  bandGroupKey,
  bandHealthy,
  bandKey,
  bandKeyDetail,
  bandKeyLabel,
  bandMatches,
  bandRank,
  measuredScore,
  presentBand,
} from "./band-qualification";
import { COLLECTION_WORDS } from "./collection";
import { fabric, findingsByHost, gradedSeverityRank, hasRib, linksByHost } from "./data";
import type { Band, Cite, CrossLayerFinding, Device, Finding, Severity, VocabularyName } from "./types";
import { recognisedKind, recognisedSeverity, SEVERITY_ORDER, unrecognisedPhrase } from "./types";

/* ── tri-state logic ────────────────────────────────────────────────────────── */

/** `unknown` = the evidence needed to decide was not collected. It is never a match. */
export type Tri = "yes" | "no" | "unknown";

/** Any `yes` wins; otherwise any `unknown` poisons the answer. An empty set decides nothing. */
const anyTri = (vals: readonly Tri[]): Tri => {
  if (vals.length === 0) return "unknown";
  let sawUnknown = false;
  for (const v of vals) {
    if (v === "yes") return "yes";
    if (v === "unknown") sawUnknown = true;
  }
  return sawUnknown ? "unknown" : "no";
};

/** Negation flips the decided states and leaves the undecided one undecided. */
const negate = (t: Tri): Tri => (t === "yes" ? "no" : t === "no" ? "yes" : "unknown");

/** Observed value -> decided; null -> undecided. The single place absence is converted. */
const triOf = (observed: string | number | null | undefined, m: Matcher): Tri =>
  observed === null || observed === undefined ? "unknown" : m.test(String(observed)) ? "yes" : "no";

/* ── value matching ─────────────────────────────────────────────────────────── */

export interface Matcher {
  test: (candidate: string) => boolean;
}

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Case-insensitive equality over the clause's OR-set, with `*` as a wildcard so `host:access*`
 * scopes a whole tier without the user knowing every hostname.
 */
const makeMatcher = (values: readonly string[]): Matcher => {
  const exact = new Set<string>();
  const patterns: RegExp[] = [];
  for (const v of values) {
    if (v.includes("*")) patterns.push(new RegExp(`^${v.split("*").map(escapeRe).join(".*")}$`, "i"));
    else exact.add(v.toLowerCase());
  }
  return {
    test: (c: string) => exact.has(c.toLowerCase()) || patterns.some((p) => p.test(c)),
  };
};

/* ── the fleet's own vocabulary, derived from the compiled fabric ───────────── */

export interface DomainValue {
  value: string;
  /** Rows carrying this value, or null where a count would be misleading (see `detail`). */
  count: number | null;
  /** Which collection the count is over, so the palette can label it honestly. */
  source: string;
  detail: string | null;
}

const deviceByHost: ReadonlyMap<string, Device> = (() => {
  const m = new Map<string, Device>();
  for (const d of fabric.devices) m.set(d.host, d);
  // `id` is the stable handle the URL carries; index it too so `host:` accepts either spelling.
  for (const d of fabric.devices) if (!m.has(d.id)) m.set(d.id, d);
  return m;
})();

/**
 * Every spelling the fleet knows for a device name a record wrote. A record names its device by
 * host; a query may carry the `id` the URL uses. Matching the raw string alone makes those two
 * spellings disagree on the same box. A name the fleet does not know has only itself — it is not
 * silently mapped onto something that looks similar.
 */
const nameSpellings = (name: string): readonly string[] => {
  const d = deviceByHost.get(name);
  return d ? [name, d.host, d.id] : [name];
};

const namesDevice = (hosts: readonly string[], m: Matcher): Tri =>
  hosts.length === 0 ? "unknown" : hosts.some((h) => nameSpellings(h).some((s) => m.test(s))) ? "yes" : "no";

const tally = <T>(items: readonly T[], of: (t: T) => string | number | null): Map<string, number> => {
  const m = new Map<string, number>();
  for (const it of items) {
    const v = of(it);
    if (v === null) continue;
    const k = String(v);
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return m;
};

/** Counted domain ordered by a fixed vocabulary, keeping only what the snapshot actually holds. */
const orderedDomain = (
  counts: Map<string, number>,
  order: readonly string[],
  source: string,
): DomainValue[] =>
  order
    .filter((v) => counts.has(v))
    .map((v) => ({ value: v, count: counts.get(v) ?? 0, source, detail: null }));

/** Counted domain with no natural vocabulary: most-used first, ties by name. */
const rankedDomain = (counts: Map<string, number>, source: string): DomainValue[] =>
  [...counts.entries()]
    .map(([value, count]) => ({ value, count, source, detail: null }))
    .sort((a, b) => b.count - a.count || cmpStr(a.value, b.value));

/** Locale-independent string order — `localeCompare` is not stable across engines/ICU builds. */
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

const memo = <T>(fn: () => T): (() => T) => {
  let cached: T | null = null;
  return () => (cached === null ? (cached = fn()) : cached);
};

/* The graded severities in order, then each severity the vocabulary does not name that the snapshot holds — offered,
   counted and described as unrecognised, never left out of the vocabulary a reader is shown (`severity:` matches it). */
const severityDomain = memo(() => {
  const counts = tally(fabric.findings, (f) => f.severity);
  return [
    ...orderedDomain(counts, SEVERITY_ORDER, "findings"),
    ...[...counts.entries()]
      .filter(([value]) => !recognisedSeverity(value))
      .sort((a, b) => cmpStr(a[0], b[0]))
      .map(([value, count]) => ({ value, count, source: "findings", detail: unrecognisedPhrase("severity", value) })),
  ];
});
const categoryDomain = memo(() => rankedDomain(tally(fabric.findings, (f) => f.category), "findings"));
const waveDomain = memo(() => rankedDomain(tally(fabric.findings, (f) => f.wave), "findings"));
/* Band values are the band owner's KEYS (core/band-qualification.ts), so a favourable band that
   partly measures missing evidence is offered as "Excellent-partial", never counted as plain
   "Excellent" (B1). */
const bandDomain = memo(() =>
  orderedDomain(tally(fabric.devices, bandKey), BAND_KEY_ORDER, "devices").map((v) => ({
    ...v,
    detail: bandKeyDetail(v.value),
  })),
);
const roleDomain = memo(() => rankedDomain(tally(fabric.devices, (d) => d.role), "devices"));
/* A kind the vocabulary does not name is offered like any other (`kind:` matches it) and described as unrecognised. */
const kindDomain = memo(() =>
  rankedDomain(tally(fabric.devices, (d) => d.kind), "devices").map((v) =>
    recognisedKind(v.value) ? v : { ...v, detail: unrecognisedPhrase("kind", v.value) },
  ),
);
const platformDomain = memo(() => rankedDomain(tally(fabric.devices, (d) => d.platform), "devices"));
const tierDomain = memo(() =>
  [...tally(fabric.devices, (d) => d.tier).entries()]
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([value, count]) => ({ value, count, source: "devices", detail: null })),
);
const modelDomain = memo(() => rankedDomain(tally(fabric.devices, (d) => d.model), "devices"));
const swDomain = memo(() => rankedDomain(tally(fabric.devices, (d) => d.swVersion), "devices"));
const layerDomain = memo(() =>
  rankedDomain(tally(fabric.crossLayer, (c) => c.layers), "cross-layer records"),
);

/**
 * Hosts carry no count: for an uncollected device "0 findings" reads as a bill of health, which is
 * exactly the false-health rendering this app exists to prevent. The detail line states the
 * collection status instead.
 */
const hostDomain = memo((): DomainValue[] =>
  [...fabric.devices]
    .map((d) => ({
      value: d.host,
      count: null,
      source: "devices",
      detail: d.collected
        ? nonEmpty([
            d.role,
            bandKey(d) !== null || presentBand(d).notMeasured ? `band ${presentBand(d).short}` : presentBand(d).legendKey === "unrecognised" ? presentBand(d).short : null,
            d.collection === "complete" ? null : COLLECTION_WORDS[d.collection],
          ]).join(" · ") || "collected"
        : "not collected — findings unknown",
    }))
    .sort((a, b) => cmpStr(a.value, b.value)),
);

/* ── is: predicates (device-scoped; lifted to other entities through devices) ── */

interface PredicateDef {
  help: string;
  fn: (d: Device) => Tri;
}

/** A device is a bridge if it touches a link the engine determined cuts the graph. A link whose
 *  centrality was never computed leaves the question open — it does not decide the device. */
const bridgeTri = (d: Device): Tri =>
  anyTri((linksByHost.get(d.host) ?? []).map((l) => (l.isBridge === null ? "unknown" : l.isBridge ? "yes" : "no")));

const IS_PREDICATES: Record<string, PredicateDef> = {
  /* The engine's collection state (core/collection.ts; acceptance B7). Where the snapshot does not state it, whether
     the collector reached a device is not decided — a device record is not proof of a collection. */
  collected: { help: "the collector reached this device", fn: (d) => (d.collection === "not stated" ? "unknown" : d.collected ? "yes" : "no") },
  uncollected: { help: "not collected, or topology-only; no evidence collected", fn: (d) => (d.collection === "not stated" ? "unknown" : d.collected ? "no" : "yes") },
  partial: { help: "the engine lists its collection as partial: it answered, but essentials are missing", fn: (d) => (d.collection === "not stated" ? "unknown" : d.collection === "partial" ? "yes" : "no") },
  inventoried: { help: "an inventory record exists", fn: (d) => (d.inventoried ? "yes" : "no") },
  uninventoried: { help: "no model/serial/software record", fn: (d) => (d.inventoried ? "no" : "yes") },
  bridge: { help: "touches a link whose loss partitions the fabric", fn: bridgeTri },
  degraded: {
    help: "scored into the Poor or Critical band (undecided where a favourable band is partial)",
    fn: bandDegraded,
  },
  healthy: {
    help: "scored into the Excellent or Good band, with every scoring domain assessed",
    fn: bandHealthy,
  },
  routable: { help: "a RIB was collected, so forwarding can be modelled", fn: (d) => (hasRib(d.host) ? "yes" : "no") },
  impacted: {
    help: "its loss is modelled to strand endpoints",
    fn: (d) =>
      d.impact === null || d.impact.stranded === null ? "unknown" : d.impact.stranded > 0 ? "yes" : "no",
  },
};

const isDomain = memo((): DomainValue[] =>
  Object.entries(IS_PREDICATES)
    .map(([value, def]) => ({
      value,
      count: fabric.devices.filter((d) => def.fn(d) === "yes").length,
      source: "devices",
      detail: def.help,
    }))
    .sort((a, b) => cmpStr(a.value, b.value)),
);

/* ── has: field-presence questions ──────────────────────────────────────────── */

interface HasDef {
  help: string;
  finding?: (f: Finding) => boolean;
  device?: (d: Device) => boolean;
  crossLayer?: (c: CrossLayerFinding) => boolean;
}

/** `has:` asks whether the record carries the field at all, so a null IS the answer "no" here —
 *  the one place absence is a decided result rather than an undecided one. */
const HAS_FIELDS: Record<string, HasDef> = {
  remediation: {
    help: "the punchlist row proposes a fix",
    finding: (f) => f.remediation !== null,
    crossLayer: (c) => c.recommendation !== null,
  },
  detail: {
    help: "explanatory prose is attached",
    finding: (f) => f.detail !== null,
    crossLayer: (c) => c.detail !== null,
  },
  category: { help: "the finding is categorised", finding: (f) => f.category !== null },
  wave: { help: "a migration wave is assigned", finding: (f) => f.wave !== null },
  devices: {
    help: "the record names at least one device",
    finding: (f) => f.devices.length > 0,
    crossLayer: (c) => c.hosts.length > 0,
  },
  priority: { help: "a priority rank was computed", finding: (f) => f.priority !== null },
  layers: { help: "the layers it spans are stated", crossLayer: (c) => c.layers !== null },
  model: { help: "a hardware model was read", device: (d) => d.model !== null },
  serial: { help: "a serial number was read", device: (d) => d.serial !== null },
  software: { help: "a software version was read", device: (d) => d.swVersion !== null },
  /* Not for a device the engine banded not-measured: the number beside that band is not a measurement. */
  score: { help: "a health score was computed", device: (d) => measuredScore(d) !== null },
  impact: { help: "a failure-impact model exists", device: (d) => d.impact !== null },
  rib: { help: "a routing table was collected", device: (d) => hasRib(d.host) },
  deductions: { help: "score deductions are itemised", device: (d) => d.deductions.length > 0 },
};

const hasDomain = memo((): DomainValue[] =>
  Object.entries(HAS_FIELDS)
    .map(([value, def]) => ({
      value,
      count: null,
      source: [def.finding ? "findings" : null, def.device ? "devices" : null, def.crossLayer ? "cross-layer" : null]
        .filter(Boolean)
        .join(", "),
      detail: def.help,
    }))
    .sort((a, b) => cmpStr(a.value, b.value)),
);

/* ── entities ───────────────────────────────────────────────────────────────── */

export type EntityKind = "finding" | "device" | "cross-layer";

const ENTITY_LABEL: Record<EntityKind, string> = {
  finding: "findings",
  device: "devices",
  "cross-layer": "cross-layer records",
};

/** Which entity a `has:` field is a field OF. Used to tell a schema difference from a data gap. */
const HAS_CARRIERS: Record<EntityKind, (def: HasDef) => boolean> = {
  finding: (def) => def.finding !== undefined,
  device: (def) => def.device !== undefined,
  "cross-layer": (def) => def.crossLayer !== undefined,
};

/* ── the key registry ───────────────────────────────────────────────────────── */

export type Applicability =
  | "direct"
  | "via-devices"
  | "via-findings"
  | "not-applicable"
  | "unrecognised"
  | "incomplete";

type TriFn<T> = (item: T, m: Matcher) => Tri;
interface Bound<T> {
  how: Exclude<Applicability, "not-applicable" | "unrecognised" | "incomplete">;
  fn: TriFn<T>;
}

/** The answer to "can this entity even be asked this clause?", when the VALUE decides it. */
interface ValueVerdict {
  applicability: Extract<Applicability, "unrecognised" | "not-applicable">;
  note: string;
}
type ValueCheck = (clause: Clause, kind: EntityKind) => ValueVerdict | null;

interface KeyDef {
  key: string;
  aliases: readonly string[];
  help: string;
  domain: () => readonly DomainValue[];
  finding: Bound<Finding> | null;
  device: Bound<Device> | null;
  crossLayer: Bound<CrossLayerFinding> | null;
  /**
   * True when the clause's value selects DEVICES by their own attributes, so the set of devices the
   * result speaks about is knowable and its collection status can be reported. Deliberately false
   * for keys whose device answer is derived FROM findings (severity/category/wave): that device set
   * is a consequence of the evidence, so using it as the scope would let a collection gap define
   * itself out of existence. Those queries are covered by the fleet-level caveat instead.
   */
  scopesDevices: boolean;
  /** Set for keys where the VALUE names the question (`has:`, `is:`) rather than the key. */
  valueCheck: ValueCheck | null;
}

/** Lift a device-level question onto a record that only names hosts. A record naming no host
 *  cannot answer a device question — that is `unknown`, not `no`. */
const liftHosts =
  (fn: TriFn<Device>): TriFn<{ hosts: readonly string[] }> =>
  (item, m) =>
    anyTri(
      item.hosts.map((h) => {
        const d = deviceByHost.get(h);
        return d ? fn(d, m) : "unknown";
      }),
    );

const viaDevicesFinding = (fn: TriFn<Device>): Bound<Finding> => ({
  how: "via-devices",
  fn: (f, m) => liftHosts(fn)({ hosts: f.devices }, m),
});
const viaDevicesCross = (fn: TriFn<Device>): Bound<CrossLayerFinding> => ({
  how: "via-devices",
  fn: (c, m) => liftHosts(fn)({ hosts: c.hosts }, m),
});

/**
 * Evidence-derived device questions (does this box have a Critical finding?) are answerable only
 * where the box was collected. For an uncollected device the punchlist's silence is the absence of
 * collection, not the absence of the problem.
 */
const viaFindings = (fn: (f: Finding, m: Matcher) => Tri): Bound<Device> => ({
  how: "via-findings",
  fn: (d, m) => {
    if (!d.collected) return "unknown";
    const fs = findingsByHost.get(d.host) ?? [];
    return anyTri(fs.map((f) => fn(f, m))) === "yes" ? "yes" : fs.some((f) => fn(f, m) === "unknown") ? "unknown" : "no";
  },
});

const deviceAttr = (pick: (d: Device) => string | number | null): Bound<Device> => ({
  how: "direct",
  fn: (d, m) => triOf(pick(d), m),
});

/** `has:layers` reads better in an error message than `has` does; the same holds for `is:bridge`. */
const spelled = (clause: Clause): string => clause.values.map((v) => `${clause.key}:${v}`).join(", ");

const hasValueCheck: ValueCheck = (clause, kind) => {
  const m = makeMatcher(clause.values);
  const hits = Object.entries(HAS_FIELDS).filter(([name]) => m.test(name));
  if (hits.length === 0)
    return {
      applicability: "unrecognised",
      note: `${spelled(clause)} names no field this data model carries, so no ${ENTITY_LABEL[kind]} can be claimed to match it.`,
    };
  if (hits.some(([, def]) => HAS_CARRIERS[kind](def))) return null;
  const carriers = [
    ...new Set(
      hits.flatMap(([, def]) =>
        (Object.keys(HAS_CARRIERS) as EntityKind[]).filter((k) => HAS_CARRIERS[k](def)).map((k) => ENTITY_LABEL[k]),
      ),
    ),
  ];
  return {
    applicability: "not-applicable",
    note: `${spelled(clause)} is a field of ${carriers.join(" and ")}, not of ${ENTITY_LABEL[kind]}. That is a difference in schema, not a gap in collection: these rows were never asked the question.`,
  };
};

const isValueCheck: ValueCheck = (clause, kind) => {
  const m = makeMatcher(clause.values);
  if (Object.keys(IS_PREDICATES).some((name) => m.test(name))) return null;
  return {
    applicability: "unrecognised",
    note: `${spelled(clause)} names no predicate this engine computes, so no ${ENTITY_LABEL[kind]} can be claimed to match it.`,
  };
};

const KEY_DEFS: readonly KeyDef[] = [
  {
    key: "severity",
    aliases: ["sev"],
    help: "engine-assigned severity of a finding",
    domain: severityDomain,
    finding: { how: "direct", fn: (f, m) => triOf(f.severity, m) },
    device: viaFindings((f, m) => triOf(f.severity, m)),
    crossLayer: { how: "direct", fn: (c, m) => triOf(c.severity, m) },
    scopesDevices: false,
    valueCheck: null,
  },
  {
    key: "category",
    aliases: ["cat"],
    help: "punchlist category",
    domain: categoryDomain,
    finding: { how: "direct", fn: (f, m) => triOf(f.category, m) },
    device: viaFindings((f, m) => triOf(f.category, m)),
    crossLayer: null,
    scopesDevices: false,
    valueCheck: null,
  },
  {
    key: "wave",
    aliases: [],
    help: "migration wave assigned to a finding",
    domain: waveDomain,
    finding: { how: "direct", fn: (f, m) => triOf(f.wave, m) },
    device: viaFindings((f, m) => triOf(f.wave, m)),
    crossLayer: null,
    scopesDevices: false,
    valueCheck: null,
  },
  {
    key: "host",
    aliases: ["device", "dev"],
    help: "hostname of a device the record names",
    domain: hostDomain,
    finding: { how: "via-devices", fn: (f, m) => namesDevice(f.devices, m) },
    device: { how: "direct", fn: (d, m) => (m.test(d.host) || m.test(d.id) ? "yes" : "no") },
    crossLayer: { how: "direct", fn: (c, m) => namesDevice(c.hosts, m) },
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "role",
    aliases: [],
    help: "topology role of the device",
    domain: roleDomain,
    finding: viaDevicesFinding((d, m) => triOf(d.role, m)),
    device: deviceAttr((d) => d.role),
    crossLayer: viaDevicesCross((d, m) => triOf(d.role, m)),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "band",
    aliases: [],
    help: "health band of the device",
    domain: bandDomain,
    finding: viaDevicesFinding((d, m) => bandMatches(d, (c) => m.test(c))),
    device: { how: "direct", fn: (d, m) => bandMatches(d, (c) => m.test(c)) },
    crossLayer: viaDevicesCross((d, m) => bandMatches(d, (c) => m.test(c))),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "tier",
    aliases: [],
    help: "layout tier the device sits on",
    domain: tierDomain,
    finding: viaDevicesFinding((d, m) => triOf(d.tier, m)),
    device: deviceAttr((d) => d.tier),
    crossLayer: viaDevicesCross((d, m) => triOf(d.tier, m)),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "kind",
    aliases: [],
    help: "node kind from the cable map",
    domain: kindDomain,
    finding: viaDevicesFinding((d, m) => triOf(d.kind, m)),
    device: deviceAttr((d) => d.kind),
    crossLayer: viaDevicesCross((d, m) => triOf(d.kind, m)),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "platform",
    aliases: ["os"],
    help: "detected platform family",
    domain: platformDomain,
    finding: viaDevicesFinding((d, m) => triOf(d.platform, m)),
    device: deviceAttr((d) => d.platform),
    crossLayer: viaDevicesCross((d, m) => triOf(d.platform, m)),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "model",
    aliases: [],
    help: "hardware model",
    domain: modelDomain,
    finding: viaDevicesFinding((d, m) => triOf(d.model, m)),
    device: deviceAttr((d) => d.model),
    crossLayer: viaDevicesCross((d, m) => triOf(d.model, m)),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "software",
    aliases: ["sw", "version"],
    help: "running software version",
    domain: swDomain,
    finding: viaDevicesFinding((d, m) => triOf(d.swVersion, m)),
    device: deviceAttr((d) => d.swVersion),
    crossLayer: viaDevicesCross((d, m) => triOf(d.swVersion, m)),
    scopesDevices: true,
    valueCheck: null,
  },
  {
    key: "layer",
    aliases: ["layers"],
    help: "layers a cross-layer record spans",
    domain: layerDomain,
    // A punchlist row cites `punchlist[n]` and carries no back-reference to a cross_layer row, so
    // the layer pair genuinely cannot be recovered for a Finding. Left null deliberately.
    finding: null,
    device: null,
    crossLayer: { how: "direct", fn: (c, m) => triOf(c.layers, m) },
    scopesDevices: false,
    valueCheck: null,
  },
  {
    key: "is",
    aliases: [],
    help: "a named device predicate",
    domain: isDomain,
    finding: viaDevicesFinding((d, m) => predicateTri(d, m)),
    device: { how: "direct", fn: (d, m) => predicateTri(d, m) },
    crossLayer: viaDevicesCross((d, m) => predicateTri(d, m)),
    scopesDevices: true,
    valueCheck: isValueCheck,
  },
  {
    key: "has",
    aliases: [],
    help: "a field the record carries",
    domain: hasDomain,
    finding: { how: "direct", fn: (f, m) => hasTri(m, (def) => (def.finding ? def.finding(f) : null)) },
    device: { how: "direct", fn: (d, m) => hasTri(m, (def) => (def.device ? def.device(d) : null)) },
    crossLayer: { how: "direct", fn: (c, m) => hasTri(m, (def) => (def.crossLayer ? def.crossLayer(c) : null)) },
    // `has:` asks about the RECORD's own schema, not about a device, so it scopes no device set.
    scopesDevices: false,
    valueCheck: hasValueCheck,
  },
];

/** An `is:` value naming no known predicate is undecidable, not false — fail closed. The clause
 *  level says so by name (`isValueCheck`); this is the per-device backstop if it ever does not. */
const predicateTri = (d: Device, m: Matcher): Tri => {
  const hits = Object.entries(IS_PREDICATES).filter(([name]) => m.test(name));
  if (hits.length === 0) return "unknown";
  return anyTri(hits.map(([, def]) => def.fn(d)));
};

const hasTri = (m: Matcher, run: (def: HasDef) => boolean | null): Tri => {
  const hits = Object.entries(HAS_FIELDS).filter(([name]) => m.test(name));
  if (hits.length === 0) return "unknown";
  const answers: Tri[] = hits.map(([, def]) => {
    const r = run(def);
    // The field is known but not carried by THIS entity type — unanswerable here.
    return r === null ? "unknown" : r ? "yes" : "no";
  });
  return anyTri(answers);
};

const KEY_BY_NAME: ReadonlyMap<string, KeyDef> = (() => {
  const m = new Map<string, KeyDef>();
  for (const def of KEY_DEFS) {
    m.set(def.key, def);
    for (const a of def.aliases) m.set(a, def);
  }
  return m;
})();

/** Canonical key names, for the palette's key menu. */
export const FILTER_KEYS: readonly string[] = KEY_DEFS.map((d) => d.key);

/** Distinct observed values for a key, or null when the key is not part of the grammar. */
export function valueDomain(key: string): DomainValue[] | null {
  const def = KEY_BY_NAME.get(key.toLowerCase());
  return def ? [...def.domain()] : null;
}

export function keyHelp(key: string): string | null {
  return KEY_BY_NAME.get(key.toLowerCase())?.help ?? null;
}

/* ── parsing ────────────────────────────────────────────────────────────────── */

export interface TokenRange {
  start: number;
  end: number;
}

export type TokenKind = "key" | "operator" | "value" | "text" | "error";

export interface QueryToken {
  kind: TokenKind;
  start: number;
  end: number;
  text: string;
  /** Index into `ParsedQuery.clauses`, or null for free text. */
  clauseIndex: number | null;
  problem: string | null;
}

export interface Clause {
  /** The key exactly as typed, lowercased. */
  key: string;
  /** The registry key it resolves to (aliases collapsed), or null when unrecognised. */
  canonicalKey: string | null;
  negated: boolean;
  /** OR-set; empty while the user has typed the colon but no value yet. */
  values: string[];
  valueRanges: TokenRange[];
  range: TokenRange;
  keyRange: TokenRange;
  recognised: boolean;
  /** No value typed yet — a clause in progress, not yet a filter. */
  incomplete: boolean;
}

/** One free-text term with the operator that governs it. */
export interface TextTerm {
  /** Lowercased, quotes and the `-` operator stripped. */
  text: string;
  negated: boolean;
  range: TokenRange;
}

export interface ParsedQuery {
  raw: string;
  clauses: Clause[];
  /** Lowercased free-text terms that must be PRESENT, ANDed. Excluded terms are in `textTerms`;
   *  they are kept apart so a highlighter cannot paint the term the user asked NOT to see. */
  terms: string[];
  termRanges: TokenRange[];
  /** Every free-text term, in input order, each carrying whether it excludes rather than requires. */
  textTerms: TextTerm[];
  tokens: QueryToken[];
  unrecognisedKeys: { key: string; range: TokenRange }[];
  /** Recognised key, legal-looking value, zero rows in THIS snapshot. */
  unmatchableValues: { key: string; value: string; range: TokenRange }[];
  /** Recognised key for which the snapshot observed no value at all. */
  unobservedKeys: string[];
  isEmpty: boolean;
}

const stripQuotes = (s: string): string =>
  s.length >= 2 && s.startsWith('"') && s.endsWith('"') ? s.slice(1, -1) : s.replace(/"/g, "");

/** Split an OR-list on commas that sit outside quotes, keeping each piece's absolute range. */
const splitValues = (raw: string, offset: number): { value: string; range: TokenRange }[] => {
  const out: { value: string; range: TokenRange }[] = [];
  let inQuote = false;
  let start = 0;
  const push = (end: number) => {
    const piece = raw.slice(start, end);
    if (piece.trim().length > 0)
      out.push({ value: stripQuotes(piece), range: { start: offset + start, end: offset + end } });
  };
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (ch === '"') inQuote = !inQuote;
    else if (ch === "," && !inQuote) {
      push(i);
      start = i + 1;
    }
  }
  push(raw.length);
  return out;
};

/** Whitespace-delimited tokens, except that whitespace inside double quotes binds. */
const rawTokens = (input: string): TokenRange[] => {
  const out: TokenRange[] = [];
  let i = 0;
  while (i < input.length) {
    while (i < input.length && /\s/.test(input[i] as string)) i++;
    if (i >= input.length) break;
    const start = i;
    let inQuote = false;
    while (i < input.length) {
      const ch = input[i] as string;
      if (ch === '"') inQuote = !inQuote;
      else if (!inQuote && /\s/.test(ch)) break;
      i++;
    }
    out.push({ start, end: i });
  }
  return out;
};

const KEY_SHAPE = /^[A-Za-z][A-Za-z0-9_-]*$/;

/**
 * The single definition of "this token is a clause": a colon outside quotes, preceded by a legal
 * key. parseQuery and suggest BOTH call it, because a palette that splits `10.0.10.50:80` into a
 * key and a value describes a grammar the engine does not implement — and then reports a term the
 * engine can search perfectly well as unanswerable.
 */
const clauseSplit = (body: string): { colon: number; keyText: string } | null => {
  let inQuote = false;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === '"') inQuote = !inQuote;
    else if (ch === ":" && !inQuote) {
      const keyText = body.slice(0, i);
      return KEY_SHAPE.test(keyText) ? { colon: i, keyText } : null;
    }
  }
  return null;
};

export function parseQuery(input: string): ParsedQuery {
  const clauses: Clause[] = [];
  const tokens: QueryToken[] = [];
  const terms: string[] = [];
  const termRanges: TokenRange[] = [];
  const textTerms: TextTerm[] = [];
  const unrecognisedKeys: { key: string; range: TokenRange }[] = [];
  const unmatchableValues: { key: string; value: string; range: TokenRange }[] = [];
  const unobservedKeys: string[] = [];

  for (const tr of rawTokens(input)) {
    const raw = input.slice(tr.start, tr.end);
    const negated = raw.startsWith("-") && raw.length > 1;
    const bodyStart = tr.start + (negated ? 1 : 0);
    const body = negated ? raw.slice(1) : raw;
    const split = clauseSplit(body);

    if (split === null) {
      /* Free text. The term is built from `body`, never from `raw`: the leading `-` is the same
         exclusion operator here as it is on a clause, and folding it into the term makes the engine
         search for the sign — which then matches nothing, gets widened by the fuzzy fallback, and
         returns unrelated rows while claiming the user's filter was applied. */
      const text = stripQuotes(body).toLowerCase().trim();
      if (text.length > 0) {
        textTerms.push({ text, negated, range: { ...tr } });
        if (!negated) {
          terms.push(text);
          termRanges.push({ ...tr });
        }
        if (negated)
          tokens.push({ kind: "operator", start: tr.start, end: bodyStart, text: "-", clauseIndex: null, problem: null });
        tokens.push({ kind: "text", start: bodyStart, end: tr.end, text: body, clauseIndex: null, problem: null });
      }
      continue;
    }

    const { colon, keyText } = split;
    const key = keyText.toLowerCase();
    const def = KEY_BY_NAME.get(key) ?? null;
    const keyRange = { start: bodyStart, end: bodyStart + colon };
    const rest = body.slice(colon + 1);
    const parts = splitValues(rest, bodyStart + colon + 1);
    /* A piece that is empty once quotes come off is a value the user has STARTED, not one they have
       typed — typing the opening quote of `category:"Compound risk"` produces exactly that. Treating
       it as the empty-string value makes the clause match nothing and empties the view mid-keystroke,
       which is the same defect the bare `key:` guard exists to prevent, one character later. */
    const typedParts = parts.filter((p) => p.value.length > 0);
    const clauseIndex = clauses.length;

    const clause: Clause = {
      key,
      canonicalKey: def ? def.key : null,
      negated,
      values: typedParts.map((p) => p.value),
      valueRanges: typedParts.map((p) => p.range),
      range: { start: tr.start, end: tr.end },
      keyRange,
      recognised: def !== null,
      incomplete: typedParts.length === 0,
    };
    clauses.push(clause);

    if (negated)
      tokens.push({ kind: "operator", start: tr.start, end: bodyStart, text: "-", clauseIndex, problem: null });
    tokens.push({
      kind: def ? "key" : "error",
      start: keyRange.start,
      end: keyRange.end,
      text: keyText,
      clauseIndex,
      problem: def ? null : `Unknown filter "${key}".`,
    });
    tokens.push({
      kind: "operator",
      start: keyRange.end,
      end: keyRange.end + 1,
      text: ":",
      clauseIndex,
      problem: null,
    });
    // Every piece is tokenised, the in-progress one included, so highlighting covers the whole input.
    for (const p of parts)
      tokens.push({
        kind: "value",
        start: p.range.start,
        end: p.range.end,
        text: input.slice(p.range.start, p.range.end),
        clauseIndex,
        problem: null,
      });

    if (!def) {
      unrecognisedKeys.push({ key, range: keyRange });
      continue;
    }

    const domain = def.domain();
    if (domain.length === 0) {
      if (!unobservedKeys.includes(def.key)) unobservedKeys.push(def.key);
      continue;
    }
    for (const p of typedParts) {
      const m = makeMatcher([p.value]);
      if (!domain.some((d) => m.test(d.value)))
        unmatchableValues.push({ key: def.key, value: p.value, range: p.range });
    }
  }

  return {
    raw: input,
    clauses,
    terms,
    termRanges,
    textTerms,
    tokens,
    unrecognisedKeys,
    unmatchableValues,
    unobservedKeys,
    isEmpty: clauses.length === 0 && textTerms.length === 0,
  };
}

/* ── free-text matching ─────────────────────────────────────────────────────── */

/**
 * Subsequence match inside a bounded window. Unbounded subsequence matching degenerates into
 * "matches everything" on long prose, so a term must appear within 3× its own length — close
 * enough to be a typo or an elision, not a coincidence of letters across a paragraph.
 */
const fuzzyWithin = (hay: string, term: string): boolean => {
  const span = term.length * 3;
  const first = term[0] as string;
  for (let s = 0; s < hay.length; s++) {
    if (hay[s] !== first) continue;
    let ti = 1;
    const limit = Math.min(hay.length, s + span);
    for (let i = s + 1; i < limit && ti < term.length; i++) if (hay[i] === term[ti]) ti++;
    if (ti === term.length) return true;
  }
  return false;
};

/** Short terms fuzz into noise; below this length only an exact substring counts. */
const MIN_FUZZY_LEN = 4;

const findingHaystack = (f: Finding): string =>
  `${f.id} ${f.title} ${f.detail ?? ""} ${f.remediation ?? ""} ${f.category ?? ""} ${f.devices.join(" ")}`.toLowerCase();

const deviceHaystack = (d: Device): string =>
  `${d.id} ${d.host} ${d.role ?? ""} ${d.kind ?? ""} ${d.model ?? ""} ${d.serial ?? ""} ${d.swVersion ?? ""} ${d.platform ?? ""} ${d.badges.join(" ")} ${d.deductions.join(" ")}`.toLowerCase();

const crossHaystack = (c: CrossLayerFinding): string =>
  `${c.id} ${c.title} ${c.detail ?? ""} ${c.recommendation ?? ""} ${c.layers ?? ""} ${c.hosts.join(" ")}`.toLowerCase();

/* ── evidence scope ─────────────────────────────────────────────────────────── */

/** A device named in a scope statement, with the snapshot path that proves its status. */
export interface DeviceRef {
  host: string;
  cite: Cite;
}

/**
 * What the devices a clause selects can be expected to have produced.
 *
 * `not-device-scoped` is a structural fact, not a missing measurement: the clause does not name
 * devices, so there is no device scope to report. It is a variant rather than a null so no reader
 * can mistake "this question is not about devices" for "no gap was found".
 */
export type ClauseScope =
  | {
      kind: "device-scope";
      /** Devices the clause's value selects. */
      inScope: number;
      collectedInScope: number;
      /** Those in scope the collector never reached — they can have produced no rows at all. */
      uncollected: DeviceRef[];
      /** Nothing in scope was collected: this result is silence, not observation. */
      evidenceBlind: boolean;
      /**
       * Devices whose OWN answer to the clause is undecided (neither in scope nor decided out) —
       * e.g. `is:healthy` on a favourable band that partly measures missing evidence (B1). Rows
       * naming only them are undetermined, and "no device matches" must not be said over them.
       */
      undecided: DeviceRef[];
    }
  | { kind: "not-device-scoped"; reason: string };

/** How much of the fleet the filtered corpus can speak for at all. */
export interface EvidenceScope {
  kind: "fleet-complete" | "fleet-partial" | "rows-self-describing";
  /** Devices the collector never reached; no evidence-derived row exists for them. */
  uncollected: DeviceRef[];
  totalDevices: number;
  note: string | null;
}

const deviceRef = (d: Device): DeviceRef => ({ host: d.host, cite: d.cite });

const MAX_NAMED_HOSTS = 4;

/** Name the devices, but bound the sentence: an unbounded host list in a caveat stops being read. */
const listHosts = (refs: readonly DeviceRef[]): string => {
  const names = refs.map((r) => r.host);
  return names.length <= MAX_NAMED_HOSTS
    ? names.join(", ")
    : `${names.slice(0, MAX_NAMED_HOSTS).join(", ")} and ${names.length - MAX_NAMED_HOSTS} more`;
};

const fleetGap = memo(() => ({
  uncollected: fabric.devices.filter((d) => !d.collected).map(deviceRef),
  total: fabric.devices.length,
}));

/* ── filtering ──────────────────────────────────────────────────────────────── */

export interface ClauseOutcome {
  clause: Clause;
  applicability: Applicability;
  matched: number;
  /** Rows the clause decided AGAINST — evidence exists and it says no. */
  excluded: number;
  /** Rows the clause could not decide. Never admitted, never counted as excluded. */
  undetermined: number;
  /** Size of the result if this one clause were dropped — the "why is this list short" number. */
  withoutThisClause: number;
  /** The collection status of the devices this clause selects, or why it selects none. */
  scope: ClauseScope;
  note: string | null;
}

export interface TextOutcome {
  /** Terms a row must contain. */
  terms: string[];
  /** Terms a row must NOT contain — the `-term` operator, applied rather than searched for. */
  excludedTerms: string[];
  /** Required terms that matched nothing literally and were widened to an approximate match. */
  fuzzyTerms: string[];
  matched: number;
  /** Rows some term decided AGAINST. */
  excluded: number;
  /** Rows no term decided against, but at least one term could not decide: the text it would have
   *  had to find (or rule out) sits in a field that was never observed. `matched + excluded +
   *  undetermined === total`. */
  undetermined: number;
}

export interface FilterResult<T> {
  items: T[];
  total: number;
  clauses: ClauseOutcome[];
  textOutcome: TextOutcome | null;
  /** Rows some gate decided AGAINST, counted once. Undecided rows are NOT in here. */
  excludedTotal: number;
  /** Rows kept out only because something could not be decided. `items + excluded + undetermined
   *  === total`, so the result-level numbers cannot contradict the per-clause ones. */
  undeterminedTotal: number;
  unrecognisedKeys: string[];
  unobservedKeys: string[];
  /** What this corpus could not have contained, whatever the query was. */
  evidenceScope: EvidenceScope;
}

interface EntitySpec<T> {
  label: string;
  kind: EntityKind;
  /**
   * True when the rows are DERIVED from collected evidence. A device the collector never reached
   * contributes no such row at all, so an empty result about it is silence, not an observation.
   * Device rows are not evidence-derived: each one carries its own `collected` flag.
   */
  evidenceDerived: boolean;
  bind: (def: KeyDef) => Bound<T> | null;
  haystack: (item: T) => string;
  /**
   * True when some field the haystack draws on was never observed for this row, so a term the
   * haystack does NOT contain may still be true of the row. A miss is then `unknown`, not `no` —
   * and a NEGATED miss is `unknown`, not `yes`. Without this, `-ios` admitted the three
   * topology-only devices (every field null, so the empty haystack "contains no ios") as definitely
   * not IOS, straight into the fabric emphasis set (critic B1, 2026-09-21). Absent means the rows
   * carry no unobservable text fields.
   */
  textUndecidable?: (item: T) => boolean;
  /** The hosts a via-devices clause resolves this row through — the same list `liftHosts` reads —
   *  so the note can say how many undetermined rows name no device the fleet knows at all. */
  hostsOf?: (item: T) => readonly string[];
}

/** The devices a clause selects, by their own attributes, with their collection status. */
const deviceScopeOf = (def: KeyDef, clause: Clause): ClauseScope => {
  const bound = def.device;
  // `scopesDevices` is only meaningful for a DIRECT device binding; checking the binding as well
  // keeps the flag and the code it describes from drifting apart.
  if (!bound || bound.how !== "direct")
    return { kind: "not-device-scoped", reason: `"${def.key}" does not select devices by their own attributes.` };
  const m = makeMatcher(clause.values);
  const answer = (d: Device): Tri => (clause.negated ? negate(bound.fn(d, m)) : bound.fn(d, m));
  const inScope = fabric.devices.filter((d) => answer(d) === "yes");
  const uncollected = inScope.filter((d) => !d.collected).map(deviceRef);
  return {
    kind: "device-scope",
    inScope: inScope.length,
    collectedInScope: inScope.length - uncollected.length,
    uncollected,
    evidenceBlind: inScope.length > 0 && uncollected.length === inScope.length,
    undecided: fabric.devices.filter((d) => answer(d) === "unknown").map(deviceRef),
  };
};

const scopeNote = (clause: Clause, label: string, scope: ClauseScope): string | null => {
  if (scope.kind !== "device-scope") return null;
  const asked = `"${clause.key}:${clause.values.join(", ")}"`;
  /* Devices whose own answer is undecided are neither in scope nor decided out, so "no device
     matches" is not said over them (B1: is:healthy over five qualified favourable bands). */
  const n = scope.undecided.length;
  const undecided =
    n === 0
      ? null
      : `${n} ${n === 1 ? "device is" : "devices are"} undecided for ${asked} (${listHosts(scope.undecided)}), so ${label} naming them are undetermined, not excluded.`;
  if (scope.inScope === 0)
    return n === 0
      ? `No device in this fleet matches ${asked}, so no ${label} could match it either.`
      : `No device in this fleet is decided to match ${asked}. ${undecided}`;
  if (scope.uncollected.length === 0) return undecided;
  const hosts = listHosts(scope.uncollected);
  return joinNotes(
    scope.evidenceBlind
      ? `Every device this names (${hosts}) was never collected, so no ${label} about it can exist. This empty result is an evidence gap, not an observation.`
      : `${scope.uncollected.length} of ${scope.inScope} devices in scope were never collected (${hosts}); ${label} naming them are unknown, not absent.`,
    undecided,
  );
};

const clauseNote = (
  applicability: Applicability,
  clause: Clause,
  def: KeyDef | null,
  label: string,
  undetermined: number,
  total: number,
  /** Of the undetermined rows, those that name no device the fleet knows (via-devices only). */
  namingNoDevice: number,
): string | null => {
  // Where the VALUE is the question (`has:`, `is:`), the message has to name the value: "has" alone
  // tells the user nothing about WHICH field went unanswered.
  const subject = def?.valueCheck ? spelled(clause) : `"${clause.canonicalKey ?? clause.key}"`;
  switch (applicability) {
    case "unrecognised":
      return `${subject} is not a filter this data model answers, so no ${label} can be claimed to match it.`;
    case "not-applicable":
      return `${subject} is not carried by ${label} and cannot be derived for them; every row is undetermined.`;
    case "incomplete":
      return `"${clause.key}:" has no value yet, so it is not filtering.`;
    case "via-devices": {
      /* Two different reasons leave a row undetermined here, and the note says which: the record
         names no device the fleet knows, or every device it names answers the question "unknown"
         itself (B1: `is:healthy` on a qualified favourable band). Attributing both to the first
         told the reader 14 findings named no device when one did. */
      const own = undetermined - namingNoDevice;
      const parts = [
        namingNoDevice > 0 ? `${namingNoDevice} of ${total} name no device the fleet knows` : null,
        own > 0 ? `${own} of ${total} name only devices whose own answer to ${subject} is itself undecided` : null,
      ].filter((x): x is string => x !== null);
      return `Resolved through each record's device list.${parts.length > 0 ? ` ${parts.join("; ")}, so they are undetermined, not excluded.` : ""}`;
    }
    case "via-findings":
      return `Resolved through each device's findings.${undetermined > 0 ? ` ${undetermined} of ${total} were never collected, so their findings are unknown — not absent.` : ""}`;
    default:
      return undetermined > 0
        ? `${undetermined} of ${total} ${label} were not observed for ${subject} and are undetermined, not excluded.`
        : null;
  }
};

const joinNotes = (...parts: (string | null)[]): string | null => {
  const kept = parts.filter((p): p is string => p !== null && p.length > 0);
  return kept.length === 0 ? null : kept.join(" ");
};

const evidenceScopeOf = (spec: { label: string; evidenceDerived: boolean }): EvidenceScope => {
  const { uncollected, total } = fleetGap();
  if (!spec.evidenceDerived)
    return {
      kind: "rows-self-describing",
      uncollected,
      totalDevices: total,
      note: "Each row states its own collection status.",
    };
  if (uncollected.length === 0)
    return { kind: "fleet-complete", uncollected, totalDevices: total, note: null };
  return {
    kind: "fleet-partial",
    uncollected,
    totalDevices: total,
    note: `${uncollected.length} of ${total} devices were never collected (${listHosts(uncollected)}). No ${spec.label} exist for them at all, so nothing here — an empty result included — is evidence about those devices.`,
  };
};

function applyClauses<T>(items: readonly T[], parsed: ParsedQuery, spec: EntitySpec<T>): FilterResult<T> {
  const total = items.length;

  /* Per-clause tri-state over every input row. Evaluated independently of the other clauses so
     the exclusion accounting below is a property of the clause, not of clause order. */
  const evaluated = parsed.clauses.map((clause) => {
    const def = clause.canonicalKey ? (KEY_BY_NAME.get(clause.canonicalKey) ?? null) : null;
    let applicability: Applicability;
    let tri: Tri[];
    let verdictNote: string | null = null;
    let scope: ClauseScope = {
      kind: "not-device-scoped",
      reason: "The clause was not evaluated against devices.",
    };

    if (clause.incomplete) {
      applicability = "incomplete";
      tri = items.map(() => "yes"); // inert while the user is still typing
      scope = { kind: "not-device-scoped", reason: "No value typed yet, so nothing is in scope." };
    } else if (!def) {
      applicability = "unrecognised";
      tri = items.map(() => "unknown");
      scope = { kind: "not-device-scoped", reason: `"${clause.key}" is not in the grammar.` };
    } else {
      // A value-level verdict comes first: `has:model` on findings is a schema difference, and
      // reporting it as "not observed" would blame collection for the shape of the data model.
      const verdict = def.valueCheck ? def.valueCheck(clause, spec.kind) : null;
      const bound = spec.bind(def);
      if (verdict) {
        applicability = verdict.applicability;
        verdictNote = verdict.note;
        tri = items.map(() => "unknown");
        scope = { kind: "not-device-scoped", reason: verdict.note };
      } else if (!bound) {
        applicability = "not-applicable";
        tri = items.map(() => "unknown");
        scope = { kind: "not-device-scoped", reason: `"${def.key}" is not carried by ${spec.label}.` };
      } else {
        applicability = bound.how;
        const m = makeMatcher(clause.values);
        tri = items.map((it) => (clause.negated ? negate(bound.fn(it, m)) : bound.fn(it, m)));
        scope =
          def.scopesDevices && spec.evidenceDerived
            ? deviceScopeOf(def, clause)
            : {
                kind: "not-device-scoped",
                reason: spec.evidenceDerived
                  ? `"${def.key}" does not select a set of devices.`
                  : "Each device row states its own collection status.",
              };
      }
    }
    return { clause, def, applicability, tri, scope, verdictNote };
  });

  /* Free text: strict substring first. A required term that matches nothing literally is widened to
     a bounded fuzzy match rather than emptying the view, and the widening is reported. */
  const haystacks = items.map((it) => spec.haystack(it));
  const fuzzyTerms: string[] = [];
  const undecidable = items.map((it) => spec.textUndecidable?.(it) === true);
  /* A hit is decided either way. A MISS is decided only when every field the haystack draws on was
     observed; otherwise the term may be in the field nobody collected, so the miss is `unknown` —
     for a required term AND for an excluded one (rule 1: unknown is admitted by neither). */
  const toTri = (hits: boolean[], negated: boolean): Tri[] =>
    hits.map((hit, i) => (hit ? (negated ? "no" : "yes") : undecidable[i] ? "unknown" : negated ? "yes" : "no"));
  const termMasks: Tri[][] = parsed.textTerms.map((t) => {
    const strict = haystacks.map((h) => h.includes(t.text));
    /* An excluded term is never widened. The widening exists so a typo does not EMPTY the view; on
       an exclusion the identical widening would silently DELETE rows the user never asked to lose,
       and the deletion would be invisible in the result. */
    if (t.negated) return toTri(strict, true);
    if (strict.some(Boolean) || t.text.length < MIN_FUZZY_LEN) return toTri(strict, false);
    fuzzyTerms.push(t.text);
    return toTri(haystacks.map((h) => fuzzyWithin(h, t.text)), false);
  });
  /** Every term must be `yes`; any `no` decides against; otherwise an `unknown` leaves it undecided. */
  const textTri: Tri[] = items.map((_, i) => {
    let sawUnknown = false;
    for (const mask of termMasks) {
      if (mask[i] === "no") return "no";
      if (mask[i] === "unknown") sawUnknown = true;
    }
    return sawUnknown ? "unknown" : "yes";
  });
  const textMask = textTri.map((t) => t === "yes");

  const passesAll = (i: number, skipClause: number | null): boolean => {
    for (let c = 0; c < evaluated.length; c++) {
      if (c === skipClause) continue;
      if (evaluated[c]!.tri[i] !== "yes") return false;
    }
    return textMask[i] === true;
  };

  const kept: T[] = [];
  let excludedTotal = 0;
  let undeterminedTotal = 0;
  for (let i = 0; i < items.length; i++) {
    if (passesAll(i, null)) {
      kept.push(items[i] as T);
      continue;
    }
    /* A row held out only by an undecidable clause was NOT decided against. Folding it into
       `excludedTotal` (as `total - kept.length` does) republishes an unknown as a decided negative
       at exactly the level the UI reads most — and contradicts the per-clause numbers beside it. */
    const decidedAgainst = textTri[i] === "no" || evaluated.some((e) => e.tri[i] === "no");
    if (decidedAgainst) excludedTotal++;
    else undeterminedTotal++;
  }

  const clauses: ClauseOutcome[] = evaluated.map((e, ci) => {
    let matched = 0;
    let excluded = 0;
    let undetermined = 0;
    for (const t of e.tri) {
      if (t === "yes") matched++;
      else if (t === "no") excluded++;
      else undetermined++;
    }
    let without = 0;
    for (let i = 0; i < items.length; i++) if (passesAll(i, ci)) without++;
    return {
      clause: e.clause,
      applicability: e.applicability,
      matched,
      excluded,
      undetermined,
      withoutThisClause: without,
      scope: e.scope,
      note: joinNotes(
        e.verdictNote ??
          clauseNote(
            e.applicability,
            e.clause,
            e.def,
            spec.label,
            undetermined,
            total,
            e.tri.filter(
              (t, i) => t === "unknown" && !(spec.hostsOf?.(items[i] as T) ?? []).some((h) => deviceByHost.has(h)),
            ).length,
          ),
        scopeNote(e.clause, spec.label, e.scope),
      ),
    };
  });

  const textMatched = textMask.filter(Boolean).length;
  const textExcluded = textTri.filter((t) => t === "no").length;

  return {
    items: kept,
    total,
    clauses,
    textOutcome:
      parsed.textTerms.length === 0
        ? null
        : {
            terms: [...parsed.terms],
            excludedTerms: parsed.textTerms.filter((t) => t.negated).map((t) => t.text),
            fuzzyTerms,
            matched: textMatched,
            excluded: textExcluded,
            undetermined: total - textMatched - textExcluded,
          },
    excludedTotal,
    undeterminedTotal,
    unrecognisedKeys: parsed.unrecognisedKeys.map((u) => u.key),
    unobservedKeys: [...parsed.unobservedKeys],
    evidenceScope: evidenceScopeOf(spec),
  };
}

const FINDING_SPEC: EntitySpec<Finding> = {
  label: "findings",
  kind: "finding",
  evidenceDerived: true,
  bind: (def) => def.finding,
  haystack: findingHaystack,
  hostsOf: (f) => f.devices,
};
const DEVICE_SPEC: EntitySpec<Device> = {
  label: "devices",
  kind: "device",
  // A device row exists for every node the cable map names, collected or not, and carries its own
  // status — so the corpus is not narrowed by collection the way the punchlist is.
  evidenceDerived: false,
  bind: (def) => def.device,
  haystack: deviceHaystack,
  // A device the collector never reached, or one whose inventory fields came back null, may carry
  // exactly the text a term asks about in the field nobody observed.
  textUndecidable: (d) =>
    !d.collected || d.role === null || d.model === null || d.serial === null || d.swVersion === null || d.platform === null,
};
const CROSS_SPEC: EntitySpec<CrossLayerFinding> = {
  label: "cross-layer records",
  kind: "cross-layer",
  evidenceDerived: true,
  bind: (def) => def.crossLayer,
  haystack: crossHaystack,
  hostsOf: (c) => c.hosts,
};

export const applyToFindings = (findings: readonly Finding[], parsed: ParsedQuery): FilterResult<Finding> =>
  applyClauses(findings, parsed, FINDING_SPEC);

export const applyToDevices = (devices: readonly Device[], parsed: ParsedQuery): FilterResult<Device> =>
  applyClauses(devices, parsed, DEVICE_SPEC);

export const applyToCrossLayer = (
  items: readonly CrossLayerFinding[],
  parsed: ParsedQuery,
): FilterResult<CrossLayerFinding> => applyClauses(items, parsed, CROSS_SPEC);

/* ── completion ─────────────────────────────────────────────────────────────── */

export interface Suggestion {
  kind: "key" | "value";
  value: string;
  /** Text to splice into the input over `SuggestResult.replace`. */
  insert: string;
  label: string;
  detail: string | null;
  count: number | null;
}

export interface SuggestResult {
  mode: "key" | "value";
  /** The key whose values are being completed, when mode is "value". */
  key: string | null;
  /** Range in the input the chosen `insert` replaces. */
  replace: TokenRange;
  suggestions: Suggestion[];
  /** Set when the menu is empty for a reason the user needs told. */
  note: string | null;
}

/**
 * Complete the token under the caret. The caret — not the end of the string — decides, so editing
 * a clause in the middle of a long query completes that clause.
 */
export function suggest(input: string, caret: number): SuggestResult {
  const pos = Math.max(0, Math.min(caret, input.length));
  const token = rawTokens(input).find((t) => pos >= t.start && pos <= t.end) ?? { start: pos, end: pos };
  const raw = input.slice(token.start, token.end);
  const negated = raw.startsWith("-") && raw.length > 1;
  const bodyStart = token.start + (negated ? 1 : 0);
  const body = negated ? raw.slice(1) : raw;
  // Same predicate the parser uses: a colon inside `10.0.10.50:80` does not make a clause, so the
  // palette must not describe that token as a filter the data model cannot answer.
  const split = clauseSplit(body);
  const colonAbs = split ? bodyStart + split.colon : -1;

  if (split && colonAbs >= 0 && pos > colonAbs) {
    // Value position: complete against the last comma-separated segment before the caret.
    const key = split.keyText.toLowerCase();
    const def = KEY_BY_NAME.get(key) ?? null;
    const valuesStart = colonAbs + 1;
    const segment = input.slice(valuesStart, pos);
    const lastComma = segment.lastIndexOf(",");
    const replaceStart = valuesStart + lastComma + 1;
    const typed = input.slice(replaceStart, pos).replace(/^"/, "").toLowerCase();
    const replace = { start: replaceStart, end: Math.max(pos, token.end) };

    if (!def)
      return {
        mode: "value",
        key,
        replace,
        suggestions: [],
        note: `"${key}" is not a filter this data model answers.`,
      };

    const domain = def.domain();
    if (domain.length === 0)
      return {
        mode: "value",
        key: def.key,
        replace,
        suggestions: [],
        note: `${def.key} was not observed on any record in this snapshot — there is nothing to filter by.`,
      };

    const candidates = domain.filter((d) => typed.length === 0 || d.value.toLowerCase().startsWith(typed));
    return {
      mode: "value",
      key: def.key,
      replace,
      suggestions: candidates.map((d) => ({
        kind: "value",
        value: d.value,
        insert: d.value.includes(" ") ? `"${d.value}"` : d.value,
        label: d.value,
        detail: d.detail ?? (d.count === null ? d.source : `${d.count} ${d.source}`),
        count: d.count,
      })),
      note:
        candidates.length === 0
          ? `No observed ${def.key} value starts with "${typed}". ${domain.length} value(s) exist in this snapshot.`
          : null,
    };
  }

  // Key position — including a bare word, and including a colon-bearing token the grammar treats as
  // free text, which is reported as free text because that is what the engine will do with it.
  const typed = (split ? split.keyText : stripQuotes(body)).toLowerCase();
  const replace = { start: bodyStart, end: split ? colonAbs : token.end };
  const candidates = KEY_DEFS.filter((d) => typed.length === 0 || d.key.startsWith(typed) || d.aliases.some((a) => a.startsWith(typed)));
  return {
    mode: "key",
    key: null,
    replace,
    suggestions: candidates.map((d) => ({
      kind: "key",
      value: d.key,
      insert: `${d.key}:`,
      label: `${d.key}:`,
      detail: d.help,
      count: d.domain().length,
    })),
    note: candidates.length === 0 ? `No filter key starts with "${typed}" — it will be matched as free text.` : null,
  };
}

/* ── cross-entity ranked search ─────────────────────────────────────────────── */

export type HitKind = "device" | "finding" | "cross-layer" | "interface" | "endpoint";

export type MatchType = "exact-id" | "exact" | "prefix" | "word" | "substring";

export interface SearchHit {
  kind: HitKind;
  id: string;
  host: string | null;
  label: string;
  detail: string | null;
  /** The field whose own content matched — the user must be able to see WHY this is a hit, so this
   *  names the field the matching STRING came from, never the group it was indexed alongside. */
  field: string;
  matchType: MatchType;
  score: number;
  cite: Cite;
}

export interface SearchResult {
  term: string;
  hits: SearchHit[];
  totalHits: number;
  truncated: boolean;
}

/** How much a match is worth depends on what it matched, not only on how it matched. */
type FieldTier = "identity" | "secondary" | "association" | "body";

const SCORES: Record<FieldTier, Record<MatchType, number>> = {
  identity: { "exact-id": 1000, exact: 1000, prefix: 700, word: 600, substring: 450 },
  secondary: { "exact-id": 820, exact: 820, prefix: 620, word: 540, substring: 400 },
  association: { "exact-id": 520, exact: 520, prefix: 420, word: 380, substring: 300 },
  body: { "exact-id": 300, exact: 300, prefix: 280, word: 260, substring: 180 },
};

/**
 * One candidate string and the field it actually came from. The field travels WITH the value rather
 * than with the group, because a composite or sibling value indexed under a neighbouring field's
 * name credits the hit to a field whose content does not contain the term at all — an explanation
 * the reader cannot check against the record in front of them.
 */
interface IndexedValue {
  field: string;
  value: string;
}

interface IndexedField {
  kind: HitKind;
  /**
   * Unique per SOURCE ROW, assigned as the index is built. `id` is not unique and cannot be: the
   * compiler emits a cross-layer rule id (`CL-09`) once per host that trips the rule — 43 records
   * share 5 ids in this snapshot — so keying the one-hit-per-record dedupe on `id` deletes 17 real
   * records for every one it keeps, invisibly, from a search meant to find evidence.
   */
  record: string;
  id: string;
  host: string | null;
  label: string;
  detail: string | null;
  cite: Cite;
  tier: FieldTier;
  values: IndexedValue[];
}

const iv = (field: string, value: string | null | undefined): IndexedValue | null =>
  typeof value === "string" && value.length > 0 ? { field, value } : null;

const ivs = (...xs: (IndexedValue | null)[]): IndexedValue[] =>
  xs.filter((x): x is IndexedValue => x !== null);

const ivList = (field: string, values: readonly (string | null | undefined)[]): IndexedValue[] =>
  ivs(...values.map((v) => iv(field, v)));

const classify = (value: string, term: string, tier: FieldTier): MatchType | null => {
  const v = value.toLowerCase();
  if (v === term) return tier === "identity" ? "exact-id" : "exact";
  if (v.startsWith(term)) return "prefix";
  if (!v.includes(term)) return null;
  // Word-boundary hit reads as intentional; a mid-token hit is weaker evidence.
  return new RegExp(`\\b${escapeRe(term)}`).test(v) ? "word" : "substring";
};

const nonEmpty = (xs: readonly (string | null | undefined)[]): string[] =>
  xs.filter((x): x is string => typeof x === "string" && x.length > 0);

/**
 * The search index. `cite` is deliberately NOT indexed: it is provenance, and indexing it would
 * make every record of a host match that host's name through its citation path, inflating a
 * hostname search with rows that do not mention the host in any field a reader can see.
 */
const searchIndex = memo((): IndexedField[] => {
  const out: IndexedField[] = [];
  const add = (f: IndexedField) => {
    if (f.values.length > 0) out.push(f);
  };
  // Row identity by construction, so it cannot be undermined by whatever the compiler puts in `id`.
  let seq = 0;

  for (const d of fabric.devices) {
    const base = {
      kind: "device" as const,
      record: String(seq++),
      id: d.id,
      host: d.host,
      label: d.host,
      detail: d.collected ? nonEmpty([d.model, d.swVersion, d.role]).join(" · ") || null : "not collected",
      cite: d.cite,
    };
    add({ ...base, tier: "identity", values: ivs(iv("host", d.host), iv("id", d.id)) });
    add({
      ...base,
      tier: "secondary",
      values: ivs(iv("model", d.model), iv("serial", d.serial), iv("software", d.swVersion)),
    });
    add({
      ...base,
      tier: "association",
      values: ivs(iv("role", d.role), iv("kind", d.kind), iv("platform", d.platform)),
    });
    add({
      ...base,
      tier: "body",
      values: [...ivList("deductions", d.deductions), ...ivs(iv("impact", d.impact?.detail ?? null))],
    });
  }

  for (const f of fabric.findings) {
    const base = {
      kind: "finding" as const,
      record: String(seq++),
      id: f.id,
      host: f.devices[0] ?? null,
      label: f.title,
      detail: f.detail,
      cite: f.cite,
    };
    add({ ...base, tier: "identity", values: ivs(iv("id", f.id)) });
    add({
      ...base,
      tier: "association",
      values: [...ivList("devices", f.devices), ...ivs(iv("category", f.category), iv("severity", f.severity))],
    });
    add({
      ...base,
      tier: "body",
      values: ivs(iv("title", f.title), iv("detail", f.detail), iv("remediation", f.remediation)),
    });
  }

  for (const c of fabric.crossLayer) {
    const base = {
      kind: "cross-layer" as const,
      record: String(seq++),
      id: c.id,
      host: c.hosts[0] ?? null,
      label: c.title,
      detail: c.detail,
      cite: c.cite,
    };
    add({ ...base, tier: "identity", values: ivs(iv("id", c.id)) });
    add({
      ...base,
      tier: "association",
      values: [...ivList("hosts", c.hosts), ...ivs(iv("layers", c.layers), iv("severity", c.severity))],
    });
    add({
      ...base,
      tier: "body",
      values: ivs(iv("title", c.title), iv("detail", c.detail), iv("recommendation", c.recommendation)),
    });
  }

  for (const [host, records] of Object.entries(fabric.interfaces)) {
    for (const r of records) {
      const id = `${host}:${r.port}`;
      const base = {
        kind: "interface" as const,
        record: String(seq++),
        id,
        host,
        label: `${host} ${r.port}`,
        detail: r.description ?? r.status,
        cite: r.cite,
      };
      // The id is this record's identity — the handle the URL carries — exactly as it is for a
      // device or a finding, so a hostname search reaches a box's ports on the strength of a string
      // that really does start with the hostname.
      add({ ...base, tier: "identity", values: ivs(iv("id", id)) });
      add({ ...base, tier: "secondary", values: ivs(iv("port", r.port)) });
      add({
        ...base,
        tier: "association",
        values: ivs(iv("host", host), iv("host+port", `${host} ${r.port}`)),
      });
      add({
        ...base,
        tier: "body",
        values: ivs(iv("description", r.description), iv("portChannel", r.portChannel), iv("status", r.status)),
      });
    }
  }

  for (const e of fabric.endpoints) {
    const id = nonEmpty([e.host, e.port, e.mac, e.ip]).join(":");
    const base = {
      kind: "endpoint" as const,
      record: String(seq++),
      id,
      host: e.host,
      label: nonEmpty([e.ip, e.mac]).join(" ") || id,
      detail: e.endpointClass,
      cite: e.cite,
    };
    // No identity entry: an endpoint's id is a join of the very fields indexed below, so indexing it
    // would credit a hit to "id" when a named field already explains it.
    add({ ...base, tier: "secondary", values: ivs(iv("ip", e.ip), iv("mac", e.mac)) });
    add({
      ...base,
      tier: "association",
      values: ivs(iv("port", e.port), iv("host", e.host), iv("vlan", e.vlan)),
    });
    add({
      ...base,
      tier: "body",
      values: ivs(iv("class", e.endpointClass), iv("vendor", e.vendor), iv("evidence", e.evidence)),
    });
  }

  return out;
});

const DEFAULT_SEARCH_LIMIT = 50;

/**
 * A TOTAL order over hits: relevance first, then the (kind, id, field, cite) identity tuple. `cite`
 * is part of it because `id` is not an identity for every kind — 18 cross-layer rows share CL-09 —
 * and without it two distinct records would compare equal and their order would rest on Array.sort.
 */
export const compareHits = (a: SearchHit, b: SearchHit): number =>
  b.score - a.score ||
  cmpStr(a.kind, b.kind) ||
  cmpStr(a.id, b.id) ||
  cmpStr(a.field, b.field) ||
  cmpStr(a.cite, b.cite);

/**
 * One search across every entity. Exactly one hit per SOURCE ROW — the best-scoring field wins — so
 * a record cannot crowd the list out by matching several of its own fields, and no record is
 * swallowed by another that happens to share its id.
 */
export function rankedSearch(term: string, opts?: { limit?: number }): SearchResult {
  const q = term.trim().toLowerCase();
  if (q.length === 0) return { term, hits: [], totalHits: 0, truncated: false };

  // Keyed kind -> source row -> best hit. Nested rather than a composite string key: every
  // printable separator can legally occur inside an id (`core1:Gi1/0/1`,
  // `access1:Gi0/2:aabb.ccdd.ee01`), and a control-character separator would put raw NUL bytes in
  // this source file. The inner key is the ROW, not the id — see IndexedField.record.
  const best = new Map<HitKind, Map<string, SearchHit>>();
  for (const f of searchIndex()) {
    let winner: { type: MatchType; field: string } | null = null;
    for (const v of f.values) {
      const t = classify(v.value, q, f.tier);
      // Ties inside one entry go to the value declared first, so the reported field is stable.
      if (t !== null && (winner === null || SCORES[f.tier][t] > SCORES[f.tier][winner.type]))
        winner = { type: t, field: v.field };
    }
    if (winner === null) continue;
    const hit: SearchHit = {
      kind: f.kind,
      id: f.id,
      host: f.host,
      label: f.label,
      detail: f.detail,
      field: winner.field,
      matchType: winner.type,
      score: SCORES[f.tier][winner.type],
      cite: f.cite,
    };
    let byRecord = best.get(f.kind);
    if (!byRecord) best.set(f.kind, (byRecord = new Map<string, SearchHit>()));
    const prev = byRecord.get(f.record);
    // Tie between two fields of the same record: the earlier-indexed (stronger-tier) field wins,
    // so the reported `field` is stable rather than dependent on iteration luck.
    if (!prev || hit.score > prev.score) byRecord.set(f.record, hit);
  }

  const hits = [...best.values()].flatMap((m) => [...m.values()]).sort(compareHits);
  const limit = opts?.limit ?? DEFAULT_SEARCH_LIMIT;
  return {
    term,
    hits: hits.slice(0, limit),
    totalHits: hits.length,
    truncated: hits.length > limit,
  };
}

/* ── grouping ───────────────────────────────────────────────────────────────── */

export type FindingGroupKey = "severity" | "category" | "wave" | "host" | "band" | "role" | "none";
export type DeviceGroupKey = "band" | "role" | "tier" | "kind" | "platform" | "collected" | "none";

export interface Group<T> {
  key: string;
  label: string;
  /** false = these rows have no observed value for the grouping key. */
  observed: boolean;
  /** Set on a group of rows whose value a CLOSED vocabulary does not name: the producer's text, exactly. */
  unrecognised?: string;
  items: T[];
}

export const UNOBSERVED_GROUP = "__unobserved__";
/** The key prefix of a group of unrecognised values; no vocabulary member and no other group key starts with it. */
export const UNRECOGNISED_GROUP_PREFIX = "__unrecognised__:";

/** A row's grouping value: text, or text a CLOSED vocabulary does not name, tagged so it can never pass for a member. */
export type GroupValue = string | { readonly unrecognised: string };

/** A closed vocabulary's grouping values, as `keysOf` should hand them to `groupItems`: a member as itself, anything
 *  else tagged unrecognised, and no value as null (the Not-observed group). */
export const vocabularyValue = (value: string | null, recognised: (v: string) => boolean): GroupValue[] | null =>
  value === null ? null : [recognised(value) ? value : { unrecognised: value }];

/**
 * THE ONE GROUPER. Every row is placed — the property a grouping over a closed vocabulary lost when this kept only the
 * keys `order` lists: the queue grouped by severity showed 128 of 146 findings once 18 carried a severity the
 * vocabulary does not name, though this comment already said rows are "never dropped" (2026-10-01 refuter). Now:
 *   - a value `order` lists, in that order;
 *   - any other plain value, after them, most rows first (ties by name) — never dropped;
 *   - an UNRECOGNISED value (tagged by `keysOf`), in a group of its own after those, keyed apart from every member
 *     and labelled `unrecognised <what> "<text>"` (core/types.ts `unrecognisedPhrase`), ordered by its text;
 *   - no value at all, in the Not-observed group, last.
 * `what` names the vocabulary for that label; a grouping with no vocabulary never tags a value.
 */
export const groupItems = <T>(
  items: readonly T[],
  keysOf: (t: T) => readonly GroupValue[] | null,
  order: readonly string[] | null,
  what: VocabularyName | null = null,
): Group<T>[] => {
  const buckets = new Map<string, T[]>();
  const strange = new Map<string, T[]>();
  const unobserved: T[] = [];
  const add = (m: Map<string, T[]>, k: string, it: T): void => {
    const list = m.get(k);
    if (list) list.push(it);
    else m.set(k, [it]);
  };
  for (const it of items) {
    const ks = keysOf(it);
    if (ks === null || ks.length === 0) {
      unobserved.push(it);
      continue;
    }
    for (const k of ks) {
      if (typeof k === "string") add(buckets, k, it);
      else add(strange, k.unrecognised, it);
    }
  }
  const bySize = (m: Map<string, T[]>) => (a: string, b: string): number => (m.get(b)?.length ?? 0) - (m.get(a)?.length ?? 0) || cmpStr(a, b);
  const listed = order ? order.filter((k) => buckets.has(k)) : [];
  const rest = [...buckets.keys()].filter((k) => !listed.includes(k)).sort(bySize(buckets));
  const groups: Group<T>[] = [...listed, ...rest].map((k) => ({ key: k, label: k, observed: true, items: buckets.get(k) ?? [] }));
  for (const text of [...strange.keys()].sort(cmpStr)) {
    groups.push({
      key: `${UNRECOGNISED_GROUP_PREFIX}${text}`,
      label: what === null ? JSON.stringify(text) : unrecognisedPhrase(what, text),
      observed: true,
      unrecognised: text,
      items: strange.get(text) ?? [],
    });
  }
  // Never folded into a value bucket and never dropped: "not observed" is a finding in itself.
  if (unobserved.length > 0)
    groups.push({ key: UNOBSERVED_GROUP, label: "Not observed", observed: false, items: unobserved });
  return groups;
};

/** Group findings. `host` is deliberately multi-membership: a finding naming three devices appears
 *  under each, because the queue is read per device. Group sizes therefore need not sum to the
 *  input length for that key alone. */
export function groupBy(findings: readonly Finding[], key: FindingGroupKey): Group<Finding>[] {
  switch (key) {
    case "severity":
      return groupItems(findings, (f) => vocabularyValue(f.severity, recognisedSeverity), SEVERITY_ORDER, "severity");
    case "category":
      return groupItems(findings, (f) => (f.category === null ? null : [f.category]), null);
    case "wave":
      return groupItems(findings, (f) => (f.wave === null ? null : [f.wave]), null);
    case "host":
      return groupItems(findings, (f) => (f.devices.length === 0 ? null : [...f.devices]), null);
    case "band":
      return bandLabelled(groupItems(findings, (f) => deviceBandValues(f.devices), BAND_GROUP_ORDER, "band"));
    case "role":
      return groupItems(findings, (f) => deviceDerived(f.devices, (d) => d.role), null);
    case "none":
      return [{ key: "all", label: "All findings", observed: true, items: [...findings] }];
  }
}

/** Band groups are keyed by the band owner's keys; their labels say "Excellent (partial)" / "not measured" in words.
 *  An unrecognised band's group keeps the label `groupItems` gave it. */
const bandLabelled = <T>(groups: Group<T>[]): Group<T>[] =>
  groups.map((g) => (g.observed && g.unrecognised === undefined ? { ...g, label: bandKeyLabel(g.key) } : g));

/** Distinct observed values of a device attribute across a finding's devices; null when nothing
 *  about those devices was observed, so the row lands in the Not-observed bucket rather than a
 *  bucket that implies knowledge. */
const deviceDerived = (hosts: readonly string[], pick: (d: Device) => string | null): string[] | null => {
  const vals = new Set<string>();
  for (const h of hosts) {
    const d = deviceByHost.get(h);
    const v = d ? pick(d) : null;
    if (v !== null) vals.add(v);
  }
  return vals.size === 0 ? null : [...vals].sort(cmpStr);
};

/** The band groups a finding's devices fall in (core/band-qualification.ts `bandGroupKey`), distinct: a scored
 *  band's key, the not-measured group, an unrecognised band (tagged); null when no device of it has a band. */
const deviceBandValues = (hosts: readonly string[]): GroupValue[] | null => {
  const plain = new Set<string>();
  const strange = new Set<string>();
  for (const h of hosts) {
    const d = deviceByHost.get(h);
    const k = d ? bandGroupKey(d) : null;
    if (k === null) continue;
    if (typeof k === "string") plain.add(k);
    else strange.add(k.unrecognised);
  }
  const out: GroupValue[] = [...[...plain].sort(cmpStr), ...[...strange].sort(cmpStr).map((unrecognised) => ({ unrecognised }))];
  return out.length === 0 ? null : out;
};

export function groupDevicesBy(devices: readonly Device[], key: DeviceGroupKey): Group<Device>[] {
  switch (key) {
    case "band":
      return bandLabelled(groupItems(devices, (d) => { const k = bandGroupKey(d); return k === null ? null : [k]; }, BAND_GROUP_ORDER, "band"));
    case "role":
      return groupItems(devices, (d) => (d.role === null ? null : [d.role]), null);
    case "tier":
      return groupItems(devices, (d) => (d.tier === null ? null : [String(d.tier)]), null);
    case "kind":
      return groupItems(devices, (d) => vocabularyValue(d.kind, recognisedKind), null, "kind");
    case "platform":
      return groupItems(devices, (d) => (d.platform === null ? null : [d.platform]), null);
    case "collected":
      /* By the engine's collection state: a partial host is its own group, never folded into "Collected", and a
         snapshot that does not state collection places its devices under Not observed. */
      return groupItems(
        devices,
        (d) =>
          d.collection === "not stated"
            ? null
            : [d.collection === "complete" ? "Collected" : d.collection === "partial" ? "Partially collected" : "Not collected"],
        ["Collected", "Partially collected", "Not collected"],
      );
    case "none":
      return [{ key: "all", label: "All devices", observed: true, items: [...devices] }];
  }
}

/* ── sorting ────────────────────────────────────────────────────────────────── */

export type FindingSortField = "severity" | "priority" | "rank" | "id" | "title" | "category" | "devices" | "wave";
export type DeviceSortField =
  | "host"
  | "score"
  | "band"
  | "tier"
  | "criticality"
  | "dataQuality"
  | "role"
  | "order";

export interface SortSpec<F extends string = string> {
  field: F;
  direction: "asc" | "desc";
}

export const FINDING_SORT_FIELDS: readonly FindingSortField[] = [
  "severity",
  "priority",
  "rank",
  "id",
  "title",
  "category",
  "devices",
  "wave",
];
export const DEVICE_SORT_FIELDS: readonly DeviceSortField[] = [
  "host",
  "score",
  "band",
  "tier",
  "criticality",
  "dataQuality",
  "role",
  "order",
];

/** A sortable cell: a comparable value, or null meaning NOT OBSERVED. Nulls sink in BOTH
 *  directions — "unknown" is not the smallest value, it is not a value at all, and a descending
 *  sort that floats unknowns to the top would present them as the extreme case. */
type Cell = number | string | null;

const cmpCell = (a: Cell, b: Cell, dir: "asc" | "desc"): number => {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const base = typeof a === "number" && typeof b === "number" ? a - b : cmpStr(String(a), String(b));
  return dir === "asc" ? base : -base;
};

/** A finding's value for a sort field: what `sortBy` orders, null meaning NOT OBSERVED (it sinks either way). */
export const findingSortCell = (f: Finding, field: FindingSortField): Cell => {
  switch (field) {
    case "severity":
      /* The graded rank; an unrecognised or unstated severity is not a point on the scale, so it sinks in either
         direction like any unobserved cell (core/data.ts `severityRank` states the position). */
      return gradedSeverityRank(f.severity);
    case "priority":
      return f.priority;
    case "rank":
      return f.rank;
    case "id":
      return f.id;
    case "title":
      return f.title.toLowerCase();
    case "category":
      return f.category === null ? null : f.category.toLowerCase();
    case "devices":
      return f.devices.length === 0 ? null : f.devices.length;
    case "wave":
      return f.wave;
  }
};

const deviceCell = (d: Device, field: DeviceSortField): Cell => {
  switch (field) {
    case "host":
      return d.host.toLowerCase();
    case "score":
      // A score the engine banded not-measured is not a measurement: it sinks, never ranks as the healthiest.
      return measuredScore(d);
    case "band":
      // The owner's rank keeps the qualification: a partial band never ties with the plain one.
      return bandRank(d);
    case "tier":
      return d.tier;
    case "criticality":
      return d.criticality;
    case "dataQuality":
      return d.dataQuality;
    case "role":
      return d.role;
    case "order":
      return d.order;
  }
};

const sortWith = <T>(
  items: readonly T[],
  specs: readonly SortSpec<string>[],
  cell: (t: T, field: string) => Cell,
  identity: (t: T) => string,
): T[] =>
  [...items].sort((a, b) => {
    for (const s of specs) {
      const r = cmpCell(cell(a, s.field), cell(b, s.field), s.direction);
      if (r !== 0) return r;
    }
    // Total order guaranteed by identity, so equal rows cannot swap between engines.
    return cmpStr(identity(a), identity(b));
  });

/** Ascending severity means most-severe first: the rank, not the word, is what is ordered. */
export const sortBy = (findings: readonly Finding[], specs: readonly SortSpec<FindingSortField>[]): Finding[] =>
  sortWith(findings, specs, (f, field) => findingSortCell(f, field as FindingSortField), (f) => f.id);

export const sortDevicesBy = (devices: readonly Device[], specs: readonly SortSpec<DeviceSortField>[]): Device[] =>
  sortWith(devices, specs, (d, field) => deviceCell(d, field as DeviceSortField), (d) => d.id);

/* ── convenience re-exports for the surfaces ────────────────────────────────── */

export type { Band, Severity };
