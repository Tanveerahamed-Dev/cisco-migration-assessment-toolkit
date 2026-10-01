/**
 * query.test.ts — the query engine measured against the REAL compiled fabric.
 *
 * Expectations over the loaded fabric are derived by INDEPENDENT inspection (raw traversal of
 * `fabric.devices` / `fabric.findings` / ..., with predicates written here), not by re-running the engine's own
 * code paths. A test that recomputes an answer with the implementation's logic agrees with the implementation's
 * bugs. Explicit synthetic absent-wave controls exercise absence even when the loaded fabric has wave labels.
 *
 * TWO TIERS (src/test-support/golden-sample.ts). The invariant tests hold on ANY compiled fabric: their subjects
 * (a host, a severity, a category, a search term) are chosen by PROPERTY from the loaded data, and their counts are
 * raw traversals, so the rename leg and the golden-snapshot leg run them unchanged. A test whose subject the loaded
 * dataset does not have at all (no uncollected device, no endpoint with an address, ...) is skipped BY NAME there,
 * and the golden block proves that on the reference sample every one of them runs. The numbers and names that are
 * facts about the tracked sample alone — 140 findings, core1's 31, "gateway" in 26 — are the contract between that
 * sample and the UI, and they live in the golden blocks at the foot of this file, where they still fail loudly if
 * the sample changes. RE-EXPRESSED 2026-09-29 (P3C-V2-3): the module constants TOTAL_FINDINGS, CORE1_FINDINGS, ...
 * that the invariant blocks used to read are gone; each of those figures is now a raw count here and a golden pin
 * there.
 */
import { describe, expect, it, vi } from "vitest";
import { fabric } from "./data";
import { dataset } from "./dataset";
import { unassessedScoringDomains } from "./band-qualification";
import { describeGolden } from "../test-support/golden-sample";
import type { Device, Finding } from "./types";
import type { SearchHit } from "./query";
import {
  applyToCrossLayer,
  applyToDevices,
  applyToFindings,
  groupBy,
  groupDevicesBy,
  parseQuery,
  rankedSearch,
  sortBy,
  sortDevicesBy,
  suggest,
  valueDomain,
} from "./query";

/* ── The data, read by raw traversal (independent of data.ts's indexes and of the engine) ──────────────────────── */

const lc = (s: string | number | null | undefined): string => (s === null || s === undefined ? "" : String(s)).toLowerCase();
const SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info"] as const;
const LEGAL_BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"] as const;
const rawByName = new Map<string, Device>();
for (const d of fabric.devices) rawByName.set(d.host, d);
for (const d of fabric.devices) if (!rawByName.has(d.id)) rawByName.set(d.id, d);
type T3 = "y" | "n" | "u";
const any3 = (ts: readonly T3[]): T3 => (ts.includes("y") ? "y" : ts.length === 0 || ts.includes("u") ? "u" : "n");
/** A device-level question lifted onto a finding through its device list: unknown for a row naming no device, or a
 *  device the fleet does not know, or one whose field was not observed. */
const viaDevices = (f: Finding, pick: (d: Device) => string | number | null, want: string): T3 =>
  any3(
    f.devices.map((h) => {
      const d = rawByName.get(h);
      if (d === undefined) return "u";
      const v = pick(d);
      return v === null ? "u" : lc(v) === lc(want) ? "y" : "n";
    }),
  );
/** Does a finding name `host` (by host or id spelling)? */
const names = (f: Finding, host: string): boolean =>
  f.devices.some((h) => {
    const d = rawByName.get(h);
    return h === host || (d !== undefined && (d.host === host || d.id === host));
  });
const countBy = <K>(xs: readonly K[]): Map<K, number> => {
  const m = new Map<K, number>();
  for (const x of xs) m.set(x, (m.get(x) ?? 0) + 1);
  return m;
};
/** The key with the most rows, ties to the smaller key: a subject chosen by property, never by name. */
const most = <K extends string | number>(m: ReadonlyMap<K, number>, ok: (k: K) => boolean = () => true): K | undefined =>
  [...m].filter(([k]) => ok(k)).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))[0]?.[0];
/** Every field free text searches on a finding. */
const rawHay = (f: Finding): string =>
  `${f.id} ${f.title} ${f.detail ?? ""} ${f.remediation ?? ""} ${f.category ?? ""} ${f.devices.join(" ")}`.toLowerCase();
const proseHay = (f: Finding): string => `${f.title} ${f.detail ?? ""} ${f.remediation ?? ""}`.toLowerCase();

const RAW = {
  findings: fabric.findings.length,
  devices: fabric.devices.length,
  sev: (s: string): number => fabric.findings.filter((f) => f.severity === s).length,
  presentSeverities: SEVERITY_ORDER.filter((s) => fabric.findings.some((f) => f.severity === s)),
  withRemediation: fabric.findings.filter((f) => f.remediation !== null).length,
  uncollected: fabric.devices.filter((d) => !d.collected).map((d) => d.host),
  nullScore: fabric.devices.filter((d) => d.score === null).length,
  nullBand: fabric.devices.filter((d) => d.band === null).length,
  nameless: fabric.findings.filter((f) => f.devices.length === 0).length,
  bridge: (() => {
    const tri = (d: Device): T3 =>
      any3(fabric.links.filter((l) => [l.a, l.b].some((e) => e === d.id || e === d.host)).map((l) => (l.isBridge === null ? "u" : l.isBridge ? "y" : "n")));
    const ts = fabric.devices.map(tri);
    return { yes: ts.filter((t) => t === "y").length, no: ts.filter((t) => t === "n").length, unknown: ts.filter((t) => t === "u").length };
  })(),
};

/* ── The subjects, chosen by property ────────────────────────────────────────────────────────────────────────────── */

/** The collected device the most findings name (the sample's core1). */
const HOST = most(countBy(fabric.findings.flatMap((f) => [...new Set(f.devices)])), (h) => rawByName.get(h)?.collected === true);
const HOST_FINDINGS = HOST === undefined ? 0 : fabric.findings.filter((f) => names(f, HOST)).length;
/** A severity that, ANDed with HOST, keeps some but not all of either side (the sample's High). */
const AND_SEV = RAW.presentSeverities.find((s) => {
  const both = fabric.findings.filter((f) => f.severity === s && HOST !== undefined && names(f, HOST)).length;
  return both > 0 && both < Math.min(RAW.sev(s), HOST_FINDINGS);
});
/** The multi-word category the most findings carry (the sample has several; "Compound risk" is pinned below). */
const CATEGORY = most(countBy(fabric.findings.map((f) => f.category).filter((c): c is string => c !== null && c.includes(" "))));
/** The observed role, band and platform the most devices carry (the sample's access, Poor and ios). */
const ROLE = most(countBy(fabric.devices.map((d) => d.role).filter((r): r is string => r !== null)));
const BAND = most(countBy(fabric.devices.map((d) => d.band).filter((b): b is NonNullable<Device["band"]> => b !== null)));
const PLATFORM = most(countBy(fabric.devices.map((d) => d.platform).filter((p): p is string => p !== null)));
/** A free-text word on which the prose fields and every searched field agree (the sample's most common is "degraded";
 *  "gateway" is pinned below). */
const TERM = [...countBy(fabric.findings.flatMap((f) => [...new Set(f.title.toLowerCase().match(/[a-z]{6,}/g) ?? [])]))]
  .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
  .map(([w]) => w)
  .find((w) => fabric.findings.every((f) => proseHay(f).includes(w) === rawHay(f).includes(w)));
const TERM_FINDINGS = TERM === undefined ? 0 : fabric.findings.filter((f) => rawHay(f).includes(TERM)).length;
/** A never-collected device no finding names (the sample's AP-floor1). */
const DARK = [...fabric.devices].sort((a, b) => (a.id < b.id ? -1 : 1)).find((d) => !d.collected && !fabric.findings.some((f) => names(f, d.host)));
/** A device kind every one of whose devices went uncollected (the sample's ap). */
const DARK_KIND = most(countBy(fabric.devices.map((d): string => d.kind).filter((k): k is string => k !== null)), (k) =>
  fabric.devices.filter((d) => d.kind === k).every((d) => !d.collected),
);
/** A tier holding both collected and uncollected devices (the sample's tier 3). */
const MIXED_TIER = [...new Set(fabric.devices.map((d) => d.tier).filter((t): t is number => t !== null))]
  .sort((a, b) => a - b)
  .find((t) => {
    const ds = fabric.devices.filter((d) => d.tier === t);
    return ds.some((d) => d.collected) && ds.some((d) => !d.collected);
  });
/** A legal severity and a legal band nothing carries (the sample's Info and Fair). */
const ABSENT_SEV = SEVERITY_ORDER.find((s) => !fabric.findings.some((f) => f.severity === s));
const ABSENT_BAND = LEGAL_BANDS.find((b) => !fabric.devices.some((d) => d.band === b));
/** The layers value the most cross-layer rows carry (the sample's L2+L3; its L1+L3 is pinned below). */
const LAYERS = most(countBy(fabric.crossLayer.map((c) => c.layers).filter((l): l is string => l !== null)));
/** An endpoint address (the sample's 10.0.10.50), and a finding naming HOST in its device list AND its title
 *  (the sample's F003). */
const EP_IP = fabric.endpoints.find((e) => e.ip !== null && e.ip !== "")?.ip ?? undefined;
const DOUBLE_NAMED = HOST === undefined ? undefined : fabric.findings.find((f) => f.devices.includes(HOST) && f.title.toLowerCase().includes(HOST.toLowerCase()));
const FIRST_FINDING = fabric.findings[0];
/** Every field free text searches on a cross-layer row. */
const xlHay = (c: (typeof fabric.crossLayer)[number]): string =>
  [c.id, ...c.hosts, c.layers, c.severity, c.title, c.detail, c.recommendation].map((v) => (v ?? "").toLowerCase()).join(" ");
/** A title word that matches cross-layer rows SHARING a rule id (the sample's rows reach 35 for "access", pinned below). */
const XL_TERM = [...countBy(fabric.crossLayer.flatMap((c) => [...new Set(c.title.toLowerCase().match(/[a-z]{6,}/g) ?? [])]))]
  .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
  .map(([w]) => w)
  .find((w) => {
    const hit = fabric.crossLayer.filter((c) => xlHay(c).includes(w));
    return new Set(hit.map((c) => c.id)).size < hit.length;
  });
/** A host-name prefix for the wildcard (a host with its last character dropped). */
const PREFIX = [...fabric.devices.map((d) => d.host)].sort().find((h) => h.length >= 3)?.slice(0, -1);

/** What the loaded dataset has, for the tests that need it. On a dataset without one, those tests are skipped BY
 *  NAME; the golden block proves every one holds on the reference sample, so none is skipped there. */
const HAS = {
  "a collected host named by findings": HOST !== undefined,
  "a severity that ANDs with that host": AND_SEV !== undefined,
  "a multi-word category": CATEGORY !== undefined,
  "an observed role": ROLE !== undefined,
  "an observed band": BAND !== undefined,
  "an observed platform": PLATFORM !== undefined,
  "a searchable title word": TERM !== undefined,
  "a never-collected device no finding names": DARK !== undefined,
  "a kind of device never collected": DARK_KIND !== undefined,
  "a tier both collected and not": MIXED_TIER !== undefined,
  "an absent legal severity and band": ABSENT_SEV !== undefined && ABSENT_BAND !== undefined,
  "a cross-layer layers value": LAYERS !== undefined,
  "an endpoint address": EP_IP !== undefined,
  "a finding naming the host in its devices and title": DOUBLE_NAMED !== undefined,
  "a finding with no device": RAW.nameless > 0,
  "an uncollected device": RAW.uncollected.length > 0,
  "a finding": FIRST_FINDING !== undefined,
  "cross-layer rows sharing an id": new Set(fabric.crossLayer.map((c) => c.id)).size < fabric.crossLayer.length,
  "a word matching cross-layer rows that share an id": XL_TERM !== undefined,
};
type Need = keyof typeof HAS;
const titled = (title: string, ...needs: Need[]): string => {
  const missing = needs.filter((n) => !HAS[n]);
  return missing.length === 0 ? title : `${title} [skipped: the loaded dataset has no ${missing.join(", no ")}]`;
};
const has = (...needs: Need[]): boolean => needs.every((n) => HAS[n]);
const need = <V>(v: V | undefined): V => {
  if (v === undefined) throw new Error("a subject the test's precondition promised is missing");
  return v;
};

const ids = <T extends { id: string }>(xs: readonly T[]): string[] => xs.map((x) => x.id);

/** Explicit absence controls: the reference sample may legitimately label every finding's wave. */
const ABSENT_WAVE_FINDINGS: Finding[] = ["synthetic-absent-wave-1", "synthetic-absent-wave-2"].map((id) => ({
  id, severity: "Medium", rank: null, priority: null, category: "Synthetic absence control",
  devices: [], wave: null, title: id, detail: null, remediation: null, cite: `synthetic.${id}`,
}));

/** Query vocabulary is memoized at module load: install an isolated synthetic dataset before importing it. */
async function absentWaveQuery(): Promise<typeof import("./query")> {
  vi.resetModules();
  const set = structuredClone(dataset);
  set.fabric.findings = structuredClone(ABSENT_WAVE_FINDINGS);
  try {
    (await import("./dataset/slot")).installDataset({
      set,
      origin: { kind: "opened-file", fileName: "synthetic-absent-wave.json", fileBytes: set.fabric.meta.sourceBytes, warnings: [] },
    });
    return await import("./query");
  } finally {
    vi.resetModules();
  }
}

/** Independent restatement of the required tie-break, so the test does not borrow the engine's
 *  own comparator to check the engine's own comparator. `cite` is in the tuple because `id` is not
 *  an identity for every kind: cross-layer rows share ids. */
const tupleBefore = (a: SearchHit, b: SearchHit): boolean => {
  for (const k of ["kind", "id", "field", "cite"] as const) if (a[k] !== b[k]) return a[k] < b[k];
  return false;
};

describe("parseQuery — grammar", () => {
  it("splits typed clauses from free text and reports exact character ranges", () => {
    const input = 'severity:Critical host:core1 gateway';
    const p = parseQuery(input);

    expect(p.clauses).toHaveLength(2);
    expect(p.clauses[0]).toMatchObject({ key: "severity", values: ["Critical"], negated: false });
    expect(p.clauses[1]).toMatchObject({ key: "host", values: ["core1"], negated: false });
    expect(p.terms).toEqual(["gateway"]);

    // Ranges must address the original string exactly, for syntax highlighting.
    const c0 = p.clauses[0]!.range;
    expect(input.slice(c0.start, c0.end)).toBe("severity:Critical");
    const c1 = p.clauses[1]!.range;
    expect(input.slice(c1.start, c1.end)).toBe("host:core1");
    const t0 = p.termRanges[0]!;
    expect(input.slice(t0.start, t0.end)).toBe("gateway");

    // Tokens are contiguous, ordered and each slice back to its own text.
    let cursor = -1;
    for (const tok of p.tokens) {
      expect(tok.start).toBeGreaterThan(cursor);
      expect(input.slice(tok.start, tok.end)).toBe(tok.text);
      cursor = tok.start;
    }
    expect(p.tokens.map((t) => t.kind)).toContain("key");
    expect(p.tokens.map((t) => t.kind)).toContain("value");
    expect(p.tokens.map((t) => t.kind)).toContain("text");
  });

  it("parses quoted multi-word values and keeps the quotes inside the clause range", () => {
    const input = 'category:"Compound risk" -severity:Info';
    const p = parseQuery(input);
    expect(p.clauses[0]!.values).toEqual(["Compound risk"]);
    expect(input.slice(p.clauses[0]!.range.start, p.clauses[0]!.range.end)).toBe(
      'category:"Compound risk"',
    );
    expect(p.clauses[1]).toMatchObject({ key: "severity", values: ["Info"], negated: true });
    expect(input.slice(p.clauses[1]!.range.start, p.clauses[1]!.range.end)).toBe("-severity:Info");
  });

  it("treats commas inside one key as OR and separate keys as AND", () => {
    const p = parseQuery("severity:Critical,High role:access");
    expect(p.clauses[0]!.values).toEqual(["Critical", "High"]);
    expect(p.clauses).toHaveLength(2);
  });

  it("parses quoted free text as a single term", () => {
    const p = parseQuery('"sole gateway"');
    expect(p.terms).toEqual(["sole gateway"]);
    expect(p.clauses).toHaveLength(0);
  });

  it("reports an unrecognised key instead of ignoring it", () => {
    const p = parseQuery("frobnicate:yes severity:High");
    expect(p.unrecognisedKeys.map((u) => u.key)).toEqual(["frobnicate"]);
    expect(p.clauses[0]!.recognised).toBe(false);
    expect(p.clauses[1]!.recognised).toBe(true);
  });

  it.runIf(has("an absent legal severity and band"))(titled("reports a recognised key whose value is absent from this snapshot", "an absent legal severity and band"), () => {
    // A legal Severity no finding carries and a legal Band no device carries (the sample's Info and Fair, pinned
    // below): an empty result must be explainable.
    const p = parseQuery(`severity:${need(ABSENT_SEV)} band:${need(ABSENT_BAND)}`);
    expect(p.unmatchableValues.map((u) => `${u.key}:${u.value}`)).toEqual([`severity:${ABSENT_SEV}`, `band:${ABSENT_BAND}`]);
  });

  it("reports a key for which the snapshot observed no values at all", async () => {
    // Every finding has wave === null. That is NOT 'no waves exist'; it is 'migration waves were never observed',
    // and the UI must be able to say so.
    const q = await absentWaveQuery();
    const p = q.parseQuery("wave:2");
    expect(p.unobservedKeys).toContain("wave");
  });
});

describe("applyToFindings — each key returns a correct, non-empty subset", () => {
  const all = fabric.findings;

  it("filters by severity", () => {
    expect(RAW.presentSeverities.length, "the fleet carries at least one severity").toBeGreaterThan(0);
    for (const s of RAW.presentSeverities) expect(applyToFindings(all, parseQuery(`severity:${s}`)).items, s).toHaveLength(RAW.sev(s));
    const [a, b] = RAW.presentSeverities;
    if (b !== undefined) expect(applyToFindings(all, parseQuery(`severity:${a},${b}`)).items).toHaveLength(RAW.sev(a!) + RAW.sev(b));
  });

  it.runIf(has("a multi-word category"))(titled("filters by category with a quoted multi-word value", "a multi-word category"), () => {
    const r = applyToFindings(all, parseQuery(`category:"${need(CATEGORY)}"`));
    expect(r.items).toHaveLength(all.filter((f) => f.category === CATEGORY).length);
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((f) => f.category === CATEGORY)).toBe(true);
  });

  it.runIf(has("a collected host named by findings"))(titled("filters by host through the finding's own device list", "a collected host named by findings"), () => {
    const r = applyToFindings(all, parseQuery(`host:${need(HOST)}`));
    expect(r.items).toHaveLength(HOST_FINDINGS);
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((f) => names(f, HOST!))).toBe(true);
  });

  it.runIf(has("an observed role", "an observed band"))(titled("filters by a device attribute the finding does not itself carry", "an observed role", "an observed band"), () => {
    const byRole = applyToFindings(all, parseQuery(`role:${need(ROLE)}`));
    expect(byRole.items).toHaveLength(all.filter((f) => viaDevices(f, (d) => d.role, ROLE!) === "y").length);
    expect(byRole.items.length).toBeGreaterThan(0);
    expect(byRole.clauses[0]!.applicability).toBe("via-devices");

    const byBand = applyToFindings(all, parseQuery(`band:${need(BAND)}`));
    expect(byBand.items).toHaveLength(all.filter((f) => viaDevices(f, (d) => d.band, BAND!) === "y").length);
  });

  it("filters by field presence", () => {
    expect(applyToFindings(all, parseQuery("has:remediation")).items).toHaveLength(RAW.withRemediation);
    expect(applyToFindings(all, parseQuery("-has:remediation")).items).toHaveLength(RAW.findings - RAW.withRemediation);
  });

  it.runIf(has("a searchable title word"))(titled("matches free text against title, detail and remediation", "a searchable title word"), () => {
    const r = applyToFindings(all, parseQuery(need(TERM)));
    expect(r.items.length).toBe(TERM_FINDINGS);
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((f) => proseHay(f).includes(TERM!))).toBe(true);
  });

  it.runIf(has("a collected host named by findings", "a severity that ANDs with that host"))(
    titled("ANDs multiple clauses with free text", "a collected host named by findings", "a severity that ANDs with that host"),
    () => {
      const r = applyToFindings(all, parseQuery(`severity:${need(AND_SEV)} host:${need(HOST)}`));
      expect(r.items.length).toBeGreaterThan(0);
      expect(r.items.every((f) => f.severity === AND_SEV && names(f, HOST!))).toBe(true);
      expect(r.items.length).toBeLessThan(Math.min(RAW.sev(AND_SEV!), HOST_FINDINGS));
    },
  );
});

describe("negation excludes exactly what it should", () => {
  const all = fabric.findings;

  it("negates a determinate clause as the complement", () => {
    for (const s of RAW.presentSeverities) {
      const pos = applyToFindings(all, parseQuery(`severity:${s}`)).items;
      const neg = applyToFindings(all, parseQuery(`-severity:${s}`)).items;
      expect(neg).toHaveLength(RAW.findings - RAW.sev(s));
      const posIds = new Set(ids(pos));
      expect(neg.some((f) => posIds.has(f.id))).toBe(false);
      expect(pos.length + neg.length).toBe(RAW.findings);
    }
  });

  it("does NOT sweep undetermined items into the negation — absence is not health", () => {
    // A device touching a link the engine proved is a bridge is `is:bridge`; one touching only links it proved are
    // not is `-is:bridge`; one touching a link whose centrality was never computed is neither. `-is:bridge` must
    // return the proven-not, never the unknown (the sample's 19 / 4 / 3 are pinned below).
    const pos = applyToDevices(fabric.devices, parseQuery("is:bridge"));
    const neg = applyToDevices(fabric.devices, parseQuery("-is:bridge"));
    expect(pos.items).toHaveLength(RAW.bridge.yes);
    expect(neg.items).toHaveLength(RAW.bridge.no);
    expect(pos.items.length + neg.items.length).toBe(RAW.devices - RAW.bridge.unknown);
    expect(neg.clauses[0]!.undetermined).toBe(RAW.bridge.unknown);
  });
});

describe("an unrecognised key never silently passes everything through", () => {
  it("returns nothing and says why", () => {
    const r = applyToFindings(fabric.findings, parseQuery("frobnicate:yes"));
    expect(r.items).toHaveLength(0);
    if (RAW.findings > 0) expect(r.items.length).not.toBe(RAW.findings);
    const outcome = r.clauses[0]!;
    expect(outcome.applicability).toBe("unrecognised");
    expect(outcome.undetermined).toBe(RAW.findings);
    expect(outcome.excluded).toBe(0);
    expect(outcome.note).toMatch(/frobnicate/);
    expect(r.unrecognisedKeys).toEqual(["frobnicate"]);
  });

  it("does not let a recognised clause launder an unrecognised one", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:High frobnicate:yes"));
    expect(r.items).toHaveLength(0);
  });

  it.runIf(has("a cross-layer layers value"))(titled("reports a key that cannot be evaluated on this entity rather than passing it", "a cross-layer layers value"), () => {
    // `layer` lives on cross-layer records. A punchlist finding cites `punchlist[n]` and carries no
    // link back to a cross_layer row, so the question is unanswerable for findings — and an
    // unanswerable question must not return a full, confident-looking list.
    const r = applyToFindings(fabric.findings, parseQuery(`layer:${need(LAYERS)}`));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.applicability).toBe("not-applicable");
    expect(r.clauses[0]!.undetermined).toBe(RAW.findings);

    const cl = applyToCrossLayer(fabric.crossLayer, parseQuery(`layer:${LAYERS}`));
    expect(cl.items).toHaveLength(fabric.crossLayer.filter((c) => lc(c.layers) === lc(LAYERS)).length);
    expect(cl.items.length).toBeGreaterThan(0);
    expect(cl.clauses[0]!.applicability).toBe("direct");
  });
});

describe("unobserved fields stay unobserved", () => {
  it("reports every finding as undetermined for wave, never as excluded", async () => {
    const q = await absentWaveQuery();
    const r = q.applyToFindings(ABSENT_WAVE_FINDINGS, q.parseQuery("wave:2"));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.undetermined).toBe(ABSENT_WAVE_FINDINGS.length);
    expect(r.clauses[0]!.excluded).toBe(0);
    expect(r.clauses[0]!.note).toMatch(/not observed/i);
  });

  it.runIf(has("an observed role", "a finding with no device"))(
    titled("treats a finding with no device list as undetermined for device-derived clauses", "an observed role", "a finding with no device"),
    () => {
      // A finding that names no device (the sample's F142, 'No QoS configured anywhere') cannot answer 'is this on
      // an access switch?'.
      const r = applyToFindings(fabric.findings, parseQuery(`role:${need(ROLE)}`));
      expect(r.clauses[0]!.undetermined).toBe(fabric.findings.filter((f) => viaDevices(f, (d) => d.role, ROLE!) === "u").length);
      const nameless = fabric.findings.filter((f) => f.devices.length === 0).map((f) => f.id);
      expect(nameless.length).toBeGreaterThan(0);
      for (const id of nameless) expect(ids(r.items)).not.toContain(id);
    },
  );

  it("treats an uncollected device as undetermined for evidence-derived clauses", () => {
    for (const s of RAW.presentSeverities) {
      const r = applyToDevices(fabric.devices, parseQuery(`severity:${s}`));
      // A collected device with a finding of that severity naming it (by host or id).
      const want = fabric.devices.filter((d) => d.collected && fabric.findings.some((f) => f.severity === s && names(f, d.host))).length;
      expect(r.items, s).toHaveLength(want);
      expect(r.clauses[0]!.applicability).toBe("via-findings");
      expect(r.clauses[0]!.undetermined, s).toBe(RAW.uncollected.length);
    }
  });
});

describe("applyToDevices", () => {
  it("filters by direct device attributes", () => {
    if (BAND !== undefined) expect(applyToDevices(fabric.devices, parseQuery(`band:${BAND}`)).items).toHaveLength(fabric.devices.filter((d) => d.band === BAND).length);
    expect(applyToDevices(fabric.devices, parseQuery("is:uncollected")).items).toHaveLength(RAW.uncollected.length);
    for (const t of new Set(fabric.devices.map((d) => d.tier).filter((x): x is number => x !== null)))
      expect(applyToDevices(fabric.devices, parseQuery(`tier:${t}`)).items, `tier ${t}`).toHaveLength(fabric.devices.filter((d) => d.tier === t).length);
    if (PLATFORM !== undefined)
      expect(applyToDevices(fabric.devices, parseQuery(`platform:${PLATFORM}`)).items).toHaveLength(fabric.devices.filter((d) => lc(d.platform) === lc(PLATFORM)).length);
  });

  it("supports a trailing wildcard on an identifier value", () => {
    const prefix = need(PREFIX);
    const r = applyToDevices(fabric.devices, parseQuery(`host:${prefix}*`));
    const starts = (s: string): boolean => s.toLowerCase().startsWith(prefix.toLowerCase());
    expect(r.items).toHaveLength(fabric.devices.filter((d) => starts(d.host) || starts(d.id)).length);
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((d) => starts(d.host) || starts(d.id))).toBe(true);
  });
});

describe("per-clause exclusion accounting — the Grafana honesty property", () => {
  /* These assert VALUES derived from the raw snapshot, not shape invariants of the implementation.
     The earlier versions of this block checked `matched + excluded + undetermined === total`,
     `withoutThisClause >= items.length` and `items.length <= matched` — all three are tautologies
     of an implementation that assigns each row exactly one tri-state and ANDs the clauses, so they
     hold just as well when the tri-states themselves are wrong. */

  it.runIf(has("a collected host named by findings"))(titled("splits each clause's input the way the raw data splits it", "a collected host named by findings"), () => {
    const r = applyToFindings(fabric.findings, parseQuery(`host:${need(HOST)}`));
    // Derived by traversal: the findings naming HOST match, a finding naming no device is unanswerable, and the
    // rest name devices that are not HOST.
    const naming = fabric.findings.filter((f) => names(f, HOST!)).length;
    const nameless = RAW.nameless;
    const c = r.clauses[0]!;
    expect([c.matched, c.excluded, c.undetermined]).toEqual([naming, RAW.findings - naming - nameless, nameless]);
  });

  it.runIf(has("a collected host named by findings", "a severity that ANDs with that host"))(
    titled("reports what each clause alone costs the result set, as a number from the data", "a collected host named by findings", "a severity that ANDs with that host"),
    () => {
      const r = applyToFindings(fabric.findings, parseQuery(`severity:${need(AND_SEV)} host:${need(HOST)}`));
      // Dropping the severity gate leaves host:HOST; dropping the host gate leaves severity:AND_SEV. Both are
      // counted here from the raw records, not from the engine.
      expect(r.clauses[0]!.withoutThisClause).toBe(fabric.findings.filter((f) => names(f, HOST!)).length);
      expect(r.clauses[1]!.withoutThisClause).toBe(RAW.sev(AND_SEV!));
      expect(r.items).toHaveLength(fabric.findings.filter((f) => f.severity === AND_SEV && names(f, HOST!)).length);
    },
  );

  it.runIf(has("an observed role", "a searchable title word"))(titled("counts free-text matches against the fields it claims to search", "an observed role", "a searchable title word"), () => {
    const sev = RAW.presentSeverities[0]!;
    const parsed = parseQuery(`severity:${sev} role:${need(ROLE)} has:remediation ${need(TERM)}`);
    const r = applyToFindings(fabric.findings, parsed);
    expect(r.total).toBe(RAW.findings);
    const matching = fabric.findings.filter((f) => rawHay(f).includes(TERM!)).length;
    expect(matching).toBeGreaterThan(0);
    expect(r.textOutcome!.matched).toBe(matching);
    expect(r.textOutcome!.excluded).toBe(RAW.findings - matching);
    expect(r.clauses[0]!.matched).toBe(RAW.sev(sev));
    expect(r.clauses[0]!.excluded).toBe(RAW.findings - RAW.sev(sev));
  });
});

describe("suggest — completions drawn from the data, never invented", () => {
  it("completes a key while the caret is in the key", () => {
    const s = suggest("sev", 3);
    expect(s.mode).toBe("key");
    expect(s.suggestions.map((x) => x.value)).toContain("severity");
    expect(s.suggestions.every((x) => x.kind === "key")).toBe(true);
  });

  it("offers exactly the severities present in the snapshot", () => {
    const s = suggest("severity:", 9);
    expect(s.mode).toBe("value");
    expect(s.key).toBe("severity");
    // A legal Severity no finding carries is not offered — offering it would invite a query that returns nothing
    // for a reason the UI could not explain.
    expect(s.suggestions.map((x) => x.value)).toEqual(RAW.presentSeverities);
    for (const x of s.suggestions) expect(x.count, x.value).toBe(RAW.sev(x.value));
  });

  it("offers real hosts and real bands, and no band the fleet does not have", () => {
    const hosts = suggest("host:", 5).suggestions.map((x) => x.value);
    const real = new Set(fabric.devices.map((d) => d.host));
    expect(hosts.length).toBeGreaterThan(0);
    expect(hosts.every((h) => real.has(h))).toBe(true);

    // A band a device carries is offered (qualified "-partial" where a favourable band sits on a device with an
    // unassessed scoring domain, as the grouping reads it); a legal band no device carries is not offered in any form.
    const bands = suggest("band:", 5).suggestions.map((x) => x.value);
    for (const b of LEGAL_BANDS) {
      const carried = fabric.devices.some((d) => d.band === b);
      const offered = bands.filter((v) => v === b || v === `${b}-partial`);
      if (carried) expect(offered.length, b).toBeGreaterThan(0);
      else expect(offered, b).toEqual([]);
    }
  });

  it("filters value candidates by the prefix already typed", () => {
    const typed = need(fabric.devices.map((d) => d.host).sort()[0]).slice(0, 3);
    const s = suggest(`host:${typed}`, 5 + typed.length);
    expect(s.suggestions.length).toBeGreaterThan(0);
    expect(s.suggestions.every((x) => x.value.toLowerCase().startsWith(typed.toLowerCase()))).toBe(true);
    expect(s.replace).toEqual({ start: 5, end: 5 + typed.length });
  });

  it("says plainly when a key has no observed values rather than showing an empty menu", async () => {
    const q = await absentWaveQuery();
    const s = q.suggest("wave:", 5);
    expect(s.suggestions).toHaveLength(0);
    expect(s.note).toMatch(/not observed/i);
  });

  it("completes the token under the caret, not the last token typed", () => {
    const input = "severity:High host:core1";
    const s = suggest(input, 13); // inside 'severity:High' -> the value token
    expect(s.mode).toBe("value");
    expect(s.key).toBe("severity");
  });

  it("exposes the same domains through valueDomain and refuses unknown keys", () => {
    const cats = [...new Set(fabric.findings.map((f) => f.category).filter((c): c is string => c !== null))];
    expect(valueDomain("category")!.map((d) => d.value).sort()).toEqual(cats.sort());
    expect(valueDomain("frobnicate")).toBeNull();
  });
});

describe("rankedSearch — one cross-entity search", () => {
  it.runIf(has("a collected host named by findings"))(titled("ranks the HOST DEVICE above findings that merely mention it", "a collected host named by findings"), () => {
    const r = rankedSearch(need(HOST));
    expect(r.hits.length).toBeGreaterThan(0);
    const first = r.hits[0]!;
    expect(first.kind).toBe("device");
    expect(first.id).toBe(rawByName.get(HOST!)!.id);

    const deviceScore = first.score;
    const findingHits = r.hits.filter((h) => h.kind === "finding");
    expect(findingHits.length).toBeGreaterThan(0);
    expect(findingHits.every((h) => h.score < deviceScore)).toBe(true);
    // The device is ranked first outright, not merely tied.
    expect(r.hits.filter((h) => h.score === deviceScore)).toHaveLength(1);
  });

  it.runIf(has("a finding naming the host in its devices and title"))(
    titled("returns one hit per record, won by that record's strongest field", "a finding naming the host in its devices and title"),
    () => {
      // A finding naming HOST in its device list AND in its title (the sample's F003) appears once, credited to the
      // device list — a record that matches five of its own fields cannot flood the result list. Identity is the
      // row's citation, not its id: `id` repeats across cross-layer rows.
      const r = rankedSearch(need(HOST), { limit: 500 });
      const keys = r.hits.map((h) => `${h.kind}|${h.cite}`);
      expect(new Set(keys).size).toBe(keys.length);
      const hit = r.hits.find((h) => h.kind === "finding" && h.id === need(DOUBLE_NAMED).id);
      expect(hit).toBeDefined();
      expect(hit!.field).toBe("devices");
      expect(hit!.matchType).toBe("exact");
    },
  );

  it.runIf(has("a finding"))(titled("finds an exact finding id above anything that mentions it", "a finding"), () => {
    const id = need(FIRST_FINDING).id;
    const r = rankedSearch(id);
    expect(r.hits[0]).toMatchObject({ kind: "finding", id, matchType: "exact-id" });
  });

  it.runIf(has("an endpoint address"))(titled("names the field that matched and carries the citation", "an endpoint address"), () => {
    const r = rankedSearch(need(EP_IP));
    const ep = r.hits.find((h) => h.kind === "endpoint");
    expect(ep).toBeDefined();
    expect(ep!.field).toBe("ip");
    expect(ep!.cite).toMatch(/^endpoint_identity\[/);
  });

  it.runIf(has("a collected host named by findings"))(titled("reaches interfaces and cross-layer records", "a collected host named by findings"), () => {
    const kinds = new Set(rankedSearch(need(HOST), { limit: 2000 }).hits.map((h) => h.kind));
    // What the raw data holds for HOST decides which kinds the search must reach.
    const d = rawByName.get(HOST!)!;
    if ((fabric.interfaces[d.host] ?? []).length > 0) expect(kinds).toContain("interface");
    if (fabric.crossLayer.some((c) => c.hosts.includes(d.host))) expect(kinds).toContain("cross-layer");
    expect(kinds).toContain("device");
  });

  it("returns nothing (and says so) for a term present nowhere", () => {
    const r = rankedSearch("zzzz-not-in-the-snapshot");
    expect(r.hits).toHaveLength(0);
    expect(r.truncated).toBe(false);
    expect(r.totalHits).toBe(0);
  });

  it.runIf(has("an observed role"))(titled("is deterministic and stably tie-broken across repeated calls", "an observed role"), () => {
    const a = rankedSearch(need(ROLE));
    const b = rankedSearch(ROLE!);
    expect(a.hits.map((h) => `${h.kind}:${h.id}:${h.field}`)).toEqual(b.hits.map((h) => `${h.kind}:${h.id}:${h.field}`));
    expect(a.hits.length).toBeGreaterThan(1);
    // Equal-scoring neighbours are ordered by (kind, id, field) — never by engine sort order.
    for (let i = 1; i < a.hits.length; i++) {
      const prev = a.hits[i - 1]!;
      const cur = a.hits[i]!;
      expect(prev.score).toBeGreaterThanOrEqual(cur.score);
      if (prev.score === cur.score) {
        expect(tupleBefore(prev, cur)).toBe(true);
      }
    }
  });

  it.runIf(has("an observed role"))(titled("reports truncation instead of silently dropping hits", "an observed role"), () => {
    const all = rankedSearch(need(ROLE), { limit: 5000 }).totalHits;
    const limit = Math.max(1, Math.min(5, all - 1));
    const r = rankedSearch(ROLE!, { limit });
    expect(all).toBeGreaterThan(limit);
    expect(r.hits).toHaveLength(limit);
    expect(r.truncated).toBe(true);
    expect(r.totalHits).toBe(all);
  });
});

describe("grouping and ordering", () => {
  it("groups findings by severity in severity order", () => {
    const groups = groupBy(fabric.findings, "severity");
    expect(groups.map((g) => g.key)).toEqual(RAW.presentSeverities);
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(RAW.findings);
    for (const g of groups) expect(g.items, g.key).toHaveLength(RAW.sev(g.key));
  });

  it("keeps an unobserved bucket separate and labelled, never folded into a value", () => {
    const groups = groupBy(ABSENT_WAVE_FINDINGS, "wave");
    expect(groups).toHaveLength(1);
    expect(groups[0]!.observed).toBe(false);
    expect(groups[0]!.label).toMatch(/not observed/i);
    expect(groups[0]!.items).toHaveLength(ABSENT_WAVE_FINDINGS.length);
  });

  it("groups devices by band in band order with the unobserved bucket last", () => {
    const groups = groupDevicesBy(fabric.devices, "band");
    if (RAW.nullBand > 0) {
      expect(groups[groups.length - 1]!.observed).toBe(false);
      expect(groups[groups.length - 1]!.items).toHaveLength(RAW.nullBand);
    } else expect(groups.every((g) => g.observed)).toBe(true);
    const observed = groups.filter((g) => g.observed).map((g) => g.key);
    /* UPDATED 2026-09-22 (acceptance B1, second failure): the old expectation ["Excellent", "Good",
       "Poor", "Critical"] filed qualified hosts under the PLAIN favourable bands although a scoring
       domain never assessed could not deduct — that expectation pinned the defect. Band order is kept:
       each favourable band's qualified key sits directly after it.
       RE-EXPRESSED 2026-09-28 (phase 3): the exact key list is a fact about one snapshot and moved to
       the golden block below (the regenerated sample collected dist1's and dist2's evidence, so a
       plain Good appeared). What holds on ANY fabric is stated here, derived independently of the
       grouping code: each collected device's key is its band, suffixed "-partial" exactly when a
       favourable band sits on a device with an unassessed scoring domain (the per-host coverage
       owner), and the observed keys are those keys in band order. */
    const FAV = new Set(["Excellent", "Good"]);
    const keyOf = (d: (typeof fabric.devices)[number]): string | null =>
      d.band === null ? null : FAV.has(d.band) && d.collected && unassessedScoringDomains(d.host).length > 0 ? `${d.band}-partial` : d.band;
    const ORDER = ["Excellent", "Excellent-partial", "Good", "Good-partial", "Fair", "Fair-partial", "Poor", "Critical"];
    const present = new Set(fabric.devices.map(keyOf).filter((k): k is string => k !== null));
    expect([...present].filter((k) => !ORDER.includes(k)), "a band key this restatement does not order").toEqual([]);
    expect(observed).toEqual(ORDER.filter((k) => present.has(k)));
    for (const g of groups.filter((x) => x.observed))
      expect(g.items.map((d) => keyOf(d)).filter((k) => k !== g.key), `group ${g.key}`).toEqual([]);
    for (const g of groups.filter((x) => x.observed && x.key.endsWith("-partial")))
      expect(g.label).toBe(`${g.key.replace(/-partial$/, "")} (partial)`);
  });

  it("sorts deterministically regardless of input order", () => {
    const spec = [{ field: "severity" as const, direction: "asc" as const }];
    const forward = ids(sortBy(fabric.findings, spec));
    const reversed = ids(sortBy([...fabric.findings].reverse(), spec));
    expect(forward).toEqual(reversed);
    expect(forward).toEqual(ids(sortBy(fabric.findings, spec)));
  });

  it("puts not-observed values last in BOTH directions", () => {
    const asc = sortDevicesBy(fabric.devices, [{ field: "score", direction: "asc" }]);
    const desc = sortDevicesBy(fabric.devices, [{ field: "score", direction: "desc" }]);
    for (const list of [asc, desc]) {
      const firstNull = list.findIndex((d) => d.score === null);
      expect(firstNull).toBe(RAW.nullScore === 0 ? -1 : RAW.devices - RAW.nullScore);
      if (firstNull >= 0) expect(list.slice(firstNull).every((d) => d.score === null)).toBe(true);
    }
    const scored = (l: typeof asc) => l.filter((d) => d.score !== null).map((d) => d.score!);
    expect(scored(asc)).toEqual([...scored(asc)].sort((a, b) => a - b));
    expect(scored(desc)).toEqual([...scored(desc)].sort((a, b) => b - a));
  });

  it("applies secondary sort specs as tie-breaks", () => {
    const sorted = sortBy(fabric.findings, [
      { field: "severity", direction: "asc" },
      { field: "id", direction: "desc" },
    ]);
    // Within each severity, ids descend (the sample's Critical run F003, F002, F001 is pinned below).
    for (const s of RAW.presentSeverities) {
      const run = ids(sorted.filter((f) => f.severity === s));
      expect(run, s).toEqual([...run].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0)));
    }
  });

  it("preserves input order through filtering", () => {
    for (const s of RAW.presentSeverities) {
      const r = applyToFindings(fabric.findings, parseQuery(`severity:${s}`));
      expect(ids(r.items), s).toEqual(fabric.findings.filter((f) => f.severity === s).map((f) => f.id));
    }
  });
});

describe("empty and degenerate input", () => {
  it("an empty query matches everything and says it is empty", () => {
    const p = parseQuery("   ");
    expect(p.isEmpty).toBe(true);
    const r = applyToFindings(fabric.findings, p);
    expect(r.items).toHaveLength(RAW.findings);
    expect(r.clauses).toHaveLength(0);
  });

  it("a bare key with no value is reported, not treated as free text", () => {
    const p = parseQuery("severity:");
    expect(p.clauses[0]!.values).toEqual([]);
    expect(p.clauses[0]!.incomplete).toBe(true);
    // An incomplete clause is not yet a filter; it must not empty the view while typing.
    const r = applyToFindings(fabric.findings, p);
    expect(r.items).toHaveLength(RAW.findings);
  });

  it("matching is case-insensitive on values but preserves the typed text in the clause", () => {
    for (const s of RAW.presentSeverities) {
      const r = applyToFindings(fabric.findings, parseQuery(`severity:${s.toLowerCase()}`));
      expect(r.items, s).toHaveLength(RAW.sev(s));
    }
    expect(parseQuery("severity:critical").clauses[0]!.values).toEqual(["critical"]);
  });
});

/* ────────────────────────────────────────────────────────────────────────────
 * Regression suite for the defects an adversarial refuter confirmed against this
 * engine. Each block states the defect it pins, and every expectation below is
 * derived by traversing the loaded fabric directly, never by re-running the code
 * path under test.
 * ──────────────────────────────────────────────────────────────────────────── */

const rawFindingsNaming = (pred: (host: string) => boolean): number => fabric.findings.filter((f) => f.devices.some(pred)).length;

describe("a never-collected device is an evidence gap, never an empty punchlist", () => {
  it.runIf(has("a never-collected device no finding names"))(
    titled("states the gap when every device the clause names was never collected", "a never-collected device no finding names"),
    () => {
      // DARK (the sample's AP-floor1) is a topology-only node. No finding names it — because nothing was collected
      // from it, not because it is clean. The result must carry that fact.
      const dark = need(DARK);
      expect(dark.collected).toBe(false);
      expect(rawFindingsNaming((h) => h === dark.host || h === dark.id)).toBe(0);

      const r = applyToFindings(fabric.findings, parseQuery(`host:${dark.host}`));
      expect(r.items).toHaveLength(0);
      const scope = r.clauses[0]!.scope;
      expect(scope.kind).toBe("device-scope");
      if (scope.kind !== "device-scope") throw new Error("unreachable");
      expect(scope.inScope).toBe(1);
      expect(scope.collectedInScope).toBe(0);
      expect(scope.evidenceBlind).toBe(true);
      expect(scope.uncollected.map((u) => u.host)).toEqual([dark.host]);
      // The claim carries its citation back into the snapshot: the device record's own.
      expect(scope.uncollected[0]!.cite).toBe(dark.cite);
      expect(r.clauses[0]!.note).toMatch(/never collected/i);
      expect(r.clauses[0]!.note).toContain(dark.host);
    },
  );

  it.runIf(has("a never-collected device no finding names"))(
    titled("says the same thing on the cross-layer surface, which cannot contradict the finding surface", "a never-collected device no finding names"),
    () => {
      const dark = need(DARK);
      const r = applyToCrossLayer(fabric.crossLayer, parseQuery(`host:${dark.host}`));
      expect(r.items).toHaveLength(fabric.crossLayer.filter((c) => c.hosts.includes(dark.host)).length);
      const scope = r.clauses[0]!.scope;
      if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
      expect(scope.evidenceBlind).toBe(true);
      expect(r.clauses[0]!.note).toMatch(/never collected/i);
    },
  );

  it.runIf(has("a kind of device never collected"))(titled("is a property of the clause's device scope, not of a list of hostnames", "a kind of device never collected"), () => {
    // `kind:<k>` names no host at all, yet every device it selects was never collected (the sample's two APs). A fix
    // scoped to the `host:` key would miss this; the honesty must come from the scope, not from a name list.
    const kind = need(DARK_KIND);
    const kindHosts = fabric.devices.filter((d) => d.kind === kind).map((d) => d.host);
    expect(kindHosts.length).toBeGreaterThan(0);
    expect(kindHosts.every((h) => RAW.uncollected.includes(h))).toBe(true);

    const r = applyToFindings(fabric.findings, parseQuery(`kind:${kind}`));
    expect(r.items).toHaveLength(0);
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.evidenceBlind).toBe(true);
    expect(scope.uncollected.map((u) => u.host).sort()).toEqual([...kindHosts].sort());
  });

  it.runIf(has("a tier both collected and not"))(titled("reports a PARTIAL gap without claiming the result is blind", "a tier both collected and not"), () => {
    // A tier holding collected and uncollected devices (the sample's tier 3: dist1, dist2 collected, AP-floor3-01
    // and wan-edge-rtr1.lab not). The findings naming a collected member are real; the silent ones are a caveat.
    const t = need(MIXED_TIER);
    const inTier = fabric.devices.filter((d) => d.tier === t);
    const silent = inTier.filter((d) => !d.collected);
    const expectedItems = fabric.findings.filter((f) => viaDevices(f, (d) => d.tier, String(t)) === "y").length;

    const r = applyToFindings(fabric.findings, parseQuery(`tier:${t}`));
    expect(r.items).toHaveLength(expectedItems);
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.inScope).toBe(inTier.length);
    expect(scope.collectedInScope).toBe(inTier.length - silent.length);
    expect(scope.evidenceBlind).toBe(false);
    expect(scope.uncollected).toHaveLength(silent.length);
    expect(r.clauses[0]!.note).toContain(`${silent.length} of ${inTier.length}`);
  });

  it.runIf(has("a collected host named by findings"))(titled("leaves a fully collected scope free of gap prose", "a collected host named by findings"), () => {
    const r = applyToFindings(fabric.findings, parseQuery(`host:${need(HOST)}`));
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.evidenceBlind).toBe(false);
    expect(scope.uncollected).toHaveLength(0);
    expect(r.clauses[0]!.note ?? "").not.toMatch(/never collected/i);
  });

  it("says a value that names no device in the fleet matched nothing for that reason", () => {
    const r = applyToFindings(fabric.findings, parseQuery("host:no-such-switch"));
    expect(r.items).toHaveLength(0);
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.inScope).toBe(0);
    expect(r.clauses[0]!.note).toMatch(/no device/i);
  });

  it.runIf(has("an uncollected device"))(titled("carries the fleet-level coverage caveat on every evidence-derived result", "an uncollected device"), () => {
    const r = applyToFindings(fabric.findings, parseQuery(""));
    expect(r.items).toHaveLength(RAW.findings);
    expect(r.evidenceScope.kind).toBe("fleet-partial");
    expect(r.evidenceScope.uncollected.map((u) => u.host).sort()).toEqual([...RAW.uncollected].sort());
    expect(r.evidenceScope.uncollected.every((u) => u.cite.length > 0)).toBe(true);
    // The note's denominator is the fleet's own (an invariant); the sample's "3 of 26" is pinned in the golden block.
    expect(r.evidenceScope.note).toContain(`${RAW.uncollected.length} of ${fabric.devices.length}`);

    // The device surface needs no such caveat: each row states its own collection status.
    const d = applyToDevices(fabric.devices, parseQuery(""));
    expect(d.evidenceScope.kind).toBe("rows-self-describing");
  });

  it("marks clauses that do not scope devices as such, rather than as an absent gap", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:High"));
    expect(r.clauses[0]!.scope.kind).toBe("not-device-scoped");
  });
});

describe("free-text negation is honoured, not swallowed into the search term", () => {
  it.runIf(has("a collected host named by findings"))(titled("excludes the rows that contain the term", "a collected host named by findings"), () => {
    const host = need(HOST);
    const expected = fabric.findings.filter((f) => !rawHay(f).includes(host.toLowerCase()));
    expect(expected.length).toBeLessThan(RAW.findings);

    const r = applyToFindings(fabric.findings, parseQuery(`-${host}`));
    expect(ids(r.items)).toEqual(expected.map((f) => f.id));
    expect(r.textOutcome!.terms).toEqual([]);
    expect(r.textOutcome!.excludedTerms).toEqual([host]);
    expect(r.textOutcome!.fuzzyTerms).toEqual([]);
  });

  it("tokenises the sign as an operator so the UI can show it was applied", () => {
    const p = parseQuery("-core1");
    expect(p.isEmpty).toBe(false);
    expect(p.textTerms).toEqual([{ text: "core1", negated: true, range: { start: 0, end: 6 } }]);
    expect(p.terms).toEqual([]);
    expect(p.tokens.map((t) => t.kind)).toEqual(["operator", "text"]);
    expect(p.tokens[0]!.text).toBe("-");
    expect(p.tokens[1]!.text).toBe("core1");
  });

  it.runIf(has("a collected host named by findings", "a severity that ANDs with that host"))(
    titled("combines with clauses", "a collected host named by findings", "a severity that ANDs with that host"),
    () => {
      const host = need(HOST);
      const expected = fabric.findings.filter((f) => f.severity === AND_SEV && !rawHay(f).includes(host.toLowerCase()));
      expect(expected.length).toBeGreaterThan(0);
      expect(applyToFindings(fabric.findings, parseQuery(`severity:${need(AND_SEV)} -${host}`)).items).toHaveLength(expected.length);
    },
  );

  it("never widens a negated term: a typo must not silently delete rows", () => {
    const r = applyToFindings(fabric.findings, parseQuery("-zzzznotpresent"));
    expect(r.items).toHaveLength(RAW.findings);
    expect(r.textOutcome!.fuzzyTerms).toEqual([]);
  });
});

describe("suggest implements the grammar parseQuery implements", () => {
  // Each of these carries a colon that KEY_SHAPE rejects, so the parser searches it as free text.
  // (`core1:Gi1/0/1` is deliberately absent: `core1` IS a legal key shape, so both the parser and
  // the palette agree it is an unrecognised KEY — they do not disagree, which is the point here.)
  const notClauses = ["10.0.10.50:80", "1.2.3.4:", "aabb.ccdd.ee01:x", "10.0.10.50:"];

  it("never calls a token a filter when the parser treats it as free text", () => {
    for (const input of notClauses) {
      const p = parseQuery(input);
      expect(p.clauses).toHaveLength(0);
      expect(p.terms).toHaveLength(1);
      const s = suggest(input, input.length);
      expect(s.mode).toBe("key");
      expect(s.note ?? "").toMatch(/free text/i);
      expect(s.note ?? "").not.toMatch(/not a filter this data model answers/);
    }
  });

  it("still names a real unrecognised key as unanswerable", () => {
    const s = suggest("frobnicate:", 11);
    expect(s.mode).toBe("value");
    expect(s.note).toMatch(/not a filter this data model answers/);
  });

  it.runIf(has("an endpoint address"))(titled("does not claim a searchable value is unanswerable", "an endpoint address"), () => {
    // A real endpoint IP; adding ":80" must not flip the palette's story about it.
    const ip = need(EP_IP);
    expect(rankedSearch(ip, { limit: 500 }).totalHits).toBeGreaterThan(0);
    expect(suggest(`${ip}:80`, ip.length + 3).suggestions).toHaveLength(0);
    expect(suggest(`${ip}:80`, ip.length + 3).note).toMatch(/free text/i);
  });
});

describe("a clause in progress never empties the view", () => {
  it("treats an opening quote as a value not yet typed", () => {
    for (const input of ['severity:"', 'host:"', 'category:""']) {
      const p = parseQuery(input);
      expect(p.clauses[0]!.incomplete).toBe(true);
      expect(p.clauses[0]!.values).toEqual([]);
      expect(p.unmatchableValues).toEqual([]);
      expect(applyToFindings(fabric.findings, p).items).toHaveLength(RAW.findings);
    }
  });

  it.runIf(has("a multi-word category"))(titled("becomes a real filter as soon as the value is typed", "a multi-word category"), () => {
    const p = parseQuery(`category:"${need(CATEGORY)}"`);
    expect(p.clauses[0]!.incomplete).toBe(false);
    expect(applyToFindings(fabric.findings, p).items).toHaveLength(fabric.findings.filter((f) => f.category === CATEGORY).length);
  });
});

describe("result-level accounting cannot contradict the per-clause accounting", () => {
  it("never books an undecidable row as excluded", () => {
    const r = applyToFindings(fabric.findings, parseQuery("frobnicate:yes"));
    expect(r.excludedTotal).toBe(0);
    expect(r.undeterminedTotal).toBe(RAW.findings);
    expect(r.items.length + r.excludedTotal + r.undeterminedTotal).toBe(RAW.findings);
  });

  it.runIf(has("a never-collected device no finding names"))(titled("separates the decided-against rows from the undecided ones", "a never-collected device no finding names"), () => {
    const r = applyToFindings(fabric.findings, parseQuery(`host:${need(DARK).host}`));
    // Every finding that names a device names one that is not DARK (decided); one naming none is undecidable.
    expect(r.excludedTotal).toBe(RAW.findings - RAW.nameless);
    expect(r.undeterminedTotal).toBe(RAW.nameless);
  });

  it("holds the three-way partition for a plain decidable clause", () => {
    for (const s of RAW.presentSeverities) {
      const r = applyToFindings(fabric.findings, parseQuery(`severity:${s}`));
      expect(r.excludedTotal, s).toBe(RAW.findings - RAW.sev(s));
      expect(r.undeterminedTotal, s).toBe(0);
    }
  });
});

describe("has: and is: answer for the value, not for the bare key", () => {
  it("calls a field the entity does not carry a schema mismatch, not a collection gap", () => {
    const r = applyToDevices(fabric.devices, parseQuery("has:category"));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.applicability).toBe("not-applicable");
    expect(r.clauses[0]!.note).toMatch(/has:category/);
    expect(r.clauses[0]!.note ?? "").not.toMatch(/not observed/i);

    const f = applyToFindings(fabric.findings, parseQuery("has:model"));
    expect(f.clauses[0]!.applicability).toBe("not-applicable");
    expect(f.clauses[0]!.note).toMatch(/has:model/);
  });

  it("calls an unknown has-field unrecognised and names it", () => {
    const r = applyToFindings(fabric.findings, parseQuery("has:frobnicate"));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.applicability).toBe("unrecognised");
    expect(r.clauses[0]!.note).toMatch(/has:frobnicate/);
  });

  it("calls an unknown is-predicate unrecognised and names it", () => {
    const r = applyToDevices(fabric.devices, parseQuery("is:nope"));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.applicability).toBe("unrecognised");
    expect(r.clauses[0]!.note).toMatch(/is:nope/);
  });

  it("still answers the fields each entity does carry", () => {
    expect(applyToFindings(fabric.findings, parseQuery("has:remediation")).items).toHaveLength(RAW.withRemediation);
    expect(applyToDevices(fabric.devices, parseQuery("is:bridge")).items).toHaveLength(RAW.bridge.yes);
    expect(applyToDevices(fabric.devices, parseQuery("has:model")).items).toHaveLength(fabric.devices.filter((d) => d.model !== null).length);
  });
});

describe("a hit names the field whose own content matched", () => {
  /** Raw per-record field values, read straight off the fabric, so the test does not ask the
   *  search index to vouch for the search index. */
  const rawFields = (hit: SearchHit): Record<string, (string | null)[]> | null => {
    if (hit.kind === "device") {
      const d = fabric.devices.find((x) => x.id === hit.id);
      return d
        ? {
            host: [d.host],
            id: [d.id],
            model: [d.model],
            serial: [d.serial],
            software: [d.swVersion],
            role: [d.role],
            kind: [d.kind],
            platform: [d.platform],
            deductions: d.deductions,
            impact: [d.impact?.detail ?? null],
          }
        : null;
    }
    if (hit.kind === "finding") {
      const f = fabric.findings.find((x) => x.id === hit.id);
      return f
        ? {
            id: [f.id],
            devices: f.devices,
            category: [f.category],
            severity: [f.severity],
            title: [f.title],
            detail: [f.detail],
            remediation: [f.remediation],
          }
        : null;
    }
    if (hit.kind === "cross-layer") {
      // By cite, not by id: cross-layer rows share ids.
      const c = fabric.crossLayer.find((x) => x.cite === hit.cite);
      return c
        ? {
            id: [c.id],
            hosts: c.hosts,
            layers: [c.layers],
            severity: [c.severity],
            title: [c.title],
            detail: [c.detail],
            recommendation: [c.recommendation],
          }
        : null;
    }
    if (hit.kind === "interface") {
      const host = hit.host ?? "";
      const port = hit.id.slice(host.length + 1);
      const r = (fabric.interfaces[host] ?? []).find((x) => x.port === port);
      return r
        ? {
            id: [hit.id],
            port: [r.port],
            host: [host],
            "host+port": [`${host} ${r.port}`],
            description: [r.description],
            portChannel: [r.portChannel],
            status: [r.status],
          }
        : null;
    }
    const e = fabric.endpoints.find(
      (x) => [x.host, x.port, x.mac, x.ip].filter((s) => s !== null && s !== "").join(":") === hit.id,
    );
    return e
      ? {
          ip: [e.ip],
          mac: [e.mac],
          port: [e.port],
          host: [e.host],
          vlan: [e.vlan],
          class: [e.endpointClass],
          vendor: [e.vendor],
          evidence: [e.evidence],
        }
      : null;
  };

  it("credits every hit to a field that really contains the term", () => {
    const terms = [HOST, ROLE, EP_IP, FIRST_FINDING?.id, TERM].filter((t): t is string => t !== undefined);
    expect(terms.length).toBeGreaterThan(0);
    for (const term of terms) {
      for (const hit of rankedSearch(term, { limit: 2000 }).hits) {
        const fields = rawFields(hit);
        expect(fields, `${hit.kind} ${hit.id} not found in the raw fabric`).not.toBeNull();
        const values = fields![hit.field];
        expect(values, `${hit.kind} ${hit.id}: unknown field "${hit.field}"`).toBeDefined();
        const carries = (values ?? []).some((v) => (v ?? "").toLowerCase().includes(term.toLowerCase()));
        expect(
          carries,
          `${hit.kind} ${hit.id} credited to "${hit.field}" = ${JSON.stringify(values)} which does not contain "${term}"`,
        ).toBe(true);
      }
    }
  });

  it.runIf(has("a collected host named by findings"))(titled("still reaches interfaces for a hostname search", "a collected host named by findings"), () => {
    const d = rawByName.get(need(HOST))!;
    const kinds = new Set(rankedSearch(HOST!, { limit: 2000 }).hits.map((h) => h.kind));
    expect(kinds.has("interface")).toBe((fabric.interfaces[d.host] ?? []).length > 0);
  });
});

describe("a record is never swallowed by another that shares its id", () => {
  it.runIf(has("cross-layer rows sharing an id", "a word matching cross-layer rows that share an id"))(
    titled("returns every cross-layer ROW that matches, not one per rule id", "cross-layer rows sharing an id", "a word matching cross-layer rows that share an id"),
    () => {
      // The compiler emits a cross-layer RULE id per host that trips the rule, so ids repeat. Keying
      // one-hit-per-record on the id therefore deletes real evidence from search results.
      const term = need(XL_TERM);
      const matches = fabric.crossLayer.filter((c) => xlHay(c).includes(term));
      expect(new Set(matches.map((c) => c.id)).size, "precondition: the matched rows share an id").toBeLessThan(matches.length);

      const hits = rankedSearch(term, { limit: 2000 }).hits.filter((h) => h.kind === "cross-layer");
      expect(hits).toHaveLength(matches.length);
      expect(new Set(hits.map((h) => h.cite)).size).toBe(hits.length);
      expect(new Set(hits.map((h) => h.cite))).toEqual(new Set(matches.map((c) => c.cite)));
    },
  );

  it.runIf(has("an observed role"))(titled("orders two records that share an id deterministically", "an observed role"), () => {
    const a = rankedSearch(need(ROLE), { limit: 2000 }).hits;
    const b = rankedSearch(ROLE!, { limit: 2000 }).hits;
    expect(a.map((h) => `${h.kind}:${h.cite}:${h.field}`)).toEqual(b.map((h) => `${h.kind}:${h.cite}:${h.field}`));
    expect(a.length).toBeGreaterThan(0);
    for (let i = 1; i < a.length; i++) {
      const prev = a[i - 1]!;
      const cur = a[i]!;
      if (prev.score === cur.score) expect(tupleBefore(prev, cur)).toBe(true);
    }
  });
});

describe("free text on devices is tri-state: an unobserved field never decides a miss", () => {
  /* Critic B1, 2026-09-21: "-ios" admitted AP-floor1, AP-floor3-01 and wan-edge-rtr1.lab — devices
     the collector never reached, every text field null — as definitely "not IOS", and fed them to
     the fabric emphasis set with undeterminedTotal 0. Checked over the whole class of negated and
     required terms, not the one term the critic typed. */
  const unobservable = new Set(
    fabric.devices
      .filter((d) => !d.collected || [d.role, d.model, d.serial, d.swVersion, d.platform].some((v) => v === null))
      .map((d) => d.id),
  );

  it.runIf(has("an uncollected device"))(titled("the fleet actually has such devices, so this test is not vacuous", "an uncollected device"), () => {
    expect(fabric.devices.filter((d) => !d.collected).length).toBeGreaterThan(0);
  });

  for (const q of ["-ios", "-nxos", "-FOC", "-access", "ios", "nxos", "catalyst", "-zzzz-no-such-text"]) {
    it(`"${q}" admits no device whose relevant fields were never observed, unless its observed text hits`, () => {
      const r = applyToDevices(fabric.devices, parseQuery(q));
      const term = q.replace(/^-/, "").toLowerCase();
      for (const d of r.items) {
        if (!unobservable.has(d.id)) continue;
        // Only a positive term may admit such a row, and only on a literal (or widened) hit.
        expect(q.startsWith("-"), `${q} admitted ${d.host}`).toBe(false);
      }
      expect(r.items.length + r.excludedTotal + r.undeterminedTotal).toBe(r.total);
      const t = r.textOutcome!;
      expect(t.matched + t.excluded + t.undetermined).toBe(r.total);
      if (q.startsWith("-") && term !== "") {
        // Every uncollected device that the term does not visibly hit is counted undecided.
        expect(r.undeterminedTotal).toBeGreaterThanOrEqual(fabric.devices.filter((d) => !d.collected && !d.host.toLowerCase().includes(term) && !d.id.toLowerCase().includes(term)).length);
      }
    });
  }

  it('"-ios" specifically: the topology-only devices are undecided, not admitted', () => {
    const r = applyToDevices(fabric.devices, parseQuery("-ios"));
    const admitted = r.items.filter((d) => !d.collected).map((d) => d.host);
    expect(admitted).toEqual([]);
    expect(r.undeterminedTotal).toBeGreaterThanOrEqual(fabric.devices.filter((d) => !d.collected && !`${d.host} ${d.id}`.toLowerCase().includes("ios")).length);
  });
});

/* ── The golden tier: facts about the tracked reference sample alone ─────────────────────────────────────────────── */

describeGolden("query counts on the reference sample", () => {
  /* The contract between the tracked sample and the UI, formerly module constants every block read. */
  const GOLDEN = {
    findings: 140,
    devices: 26,
    sev: { Critical: 3, High: 99, Medium: 33, Low: 5 },
    compoundRisk: 10,
    core1: 31,
    accessRole: 110,
    poorBand: 75,
    withRemediation: 60,
    uncollected: 3,
    bridge: { yes: 19, no: 4, unknown: 3 },
    poorBandDevices: 12,
    devicesWithCritical: 12,
  };

  it("every invariant test's precondition holds here, so none of them is skipped on the reference sample", () => {
    expect(Object.entries(HAS).filter(([, v]) => !v).map(([k]) => k)).toEqual([]);
  });

  it("the raw counts are the sample's", () => {
    expect(RAW.findings).toBe(GOLDEN.findings);
    expect(RAW.devices).toBe(GOLDEN.devices);
    expect(RAW.presentSeverities).toEqual(["Critical", "High", "Medium", "Low"]);
    for (const [s, n] of Object.entries(GOLDEN.sev)) expect(RAW.sev(s), s).toBe(n);
    expect(RAW.withRemediation).toBe(GOLDEN.withRemediation);
    expect(RAW.uncollected).toHaveLength(GOLDEN.uncollected);
    expect(RAW.nullBand).toBe(GOLDEN.uncollected);
    expect(RAW.nullScore).toBe(GOLDEN.uncollected);
    expect(RAW.bridge).toEqual(GOLDEN.bridge);
    expect(RAW.nameless).toBe(1);
  });

  it("the subjects the invariant tier picks by property are the sample's named ones", () => {
    expect(HOST).toBe("core1");
    expect(HOST_FINDINGS).toBe(GOLDEN.core1);
    expect(AND_SEV).toBe("High");
    expect(ROLE).toBe("access");
    expect(BAND).toBe("Poor");
    expect(PLATFORM).toBe("ios");
    expect(TERM).toBe("degraded");
    expect(DARK?.host).toBe("AP-floor1");
    expect(DARK?.cite).toBe("cable_map.nodes[host=AP-floor1]");
    expect(DARK_KIND).toBe("ap");
    expect(MIXED_TIER).toBe(3);
    expect([ABSENT_SEV, ABSENT_BAND]).toEqual(["Info", "Fair"]);
    expect(EP_IP).toBe("10.0.10.50");
    expect(DOUBLE_NAMED?.id).toBe("F003");
    expect(FIRST_FINDING?.id).toBe("F001");
    expect(fabric.findings.find((f) => f.devices.length === 0)?.id).toBe("F137");
  });

  it("the engine's answers on the sample", () => {
    const all = fabric.findings;
    const n = (q: string): number => applyToFindings(all, parseQuery(q)).items.length;
    expect(n("severity:Critical")).toBe(3);
    expect(n("severity:High")).toBe(99);
    expect(n("severity:Critical,High")).toBe(102);
    expect(n('category:"Compound risk"')).toBe(GOLDEN.compoundRisk);
    expect(n("host:core1")).toBe(GOLDEN.core1);
    expect(n("role:access")).toBe(GOLDEN.accessRole);
    expect(n("band:Poor")).toBe(GOLDEN.poorBand);
    expect(n("-has:remediation")).toBe(80);
    expect(n("gateway")).toBe(26);
    expect(n("severity:High -core1")).toBe(83);
    expect(n("-core1")).toBe(140 - 31);
    const role = applyToFindings(all, parseQuery("role:access"));
    expect(role.clauses[0]!.undetermined).toBe(1);
    expect(ids(role.items)).not.toContain("F137");
    const hostSplit = applyToFindings(all, parseQuery("host:core1")).clauses[0]!;
    expect([hostSplit.matched, hostSplit.excluded, hostSplit.undetermined]).toEqual([31, 108, 1]);
    const dev = (q: string): number => applyToDevices(fabric.devices, parseQuery(q)).items.length;
    expect(dev("severity:Critical")).toBe(GOLDEN.devicesWithCritical);
    expect(dev("band:Poor")).toBe(GOLDEN.poorBandDevices);
    expect(dev("tier:1")).toBe(17);
    expect(dev("platform:ios")).toBe(22);
    expect(dev("host:access*")).toBe(17);
    expect(applyToFindings(all, parseQuery("host:AP-floor1")).excludedTotal).toBe(139);
    expect(applyToCrossLayer(fabric.crossLayer, parseQuery("layer:L1+L3")).items).toHaveLength(3);
    const tier3 = applyToFindings(all, parseQuery("tier:3"));
    expect(tier3.items).toHaveLength(5);
    expect(tier3.clauses[0]!.note).toMatch(/2 of 4/);
    const critical = sortBy(all, [
      { field: "severity", direction: "asc" },
      { field: "id", direction: "desc" },
    ]).filter((f) => f.severity === "Critical");
    expect(ids(critical)).toEqual(["F003", "F002", "F001"]);
    expect(suggest("severity:", 9).suggestions.map((x) => x.value)).toEqual(["Critical", "High", "Medium", "Low"]);
    expect(valueDomain("category")!.map((d) => d.value)).toContain("Compound risk");
    const access = fabric.crossLayer.filter((c) => xlHay(c).includes("access"));
    expect(access).toHaveLength(35);
    expect(rankedSearch("access", { limit: 2000 }).hits.filter((h) => h.kind === "cross-layer")).toHaveLength(35);
    const f003 = rankedSearch("core1", { limit: 500 }).hits.find((h) => h.kind === "finding" && h.id === "F003");
    expect(f003?.field).toBe("devices");
    expect(rankedSearch("core1").hits[0]).toMatchObject({ kind: "device", id: "core1" });
  });

  it("tier:1 holds the 17 access switches; 3 of 26 devices were never collected; 43 cross-layer rows share 5 ids", () => {
    expect(applyToDevices(fabric.devices, parseQuery("tier:1")).items).toHaveLength(17);
    expect(applyToFindings(fabric.findings, parseQuery("")).evidenceScope.note).toMatch(/3 of 26/);
    expect(fabric.crossLayer.length).toBe(43);
    expect(new Set(fabric.crossLayer.map((c) => c.id)).size).toBe(5);
  });
});

describeGolden("query grouping on the reference sample", () => {
  it("band groups are Excellent-partial, Good, Good-partial, Poor, Critical, then the unobserved bucket", () => {
    const groups = groupDevicesBy(fabric.devices, "band");
    expect(groups.filter((g) => g.observed).map((g) => g.key)).toEqual(["Excellent-partial", "Good", "Good-partial", "Poor", "Critical"]);
    expect(groups.find((g) => g.key === "Excellent-partial")?.label).toBe("Excellent (partial)");
    expect(groups.find((g) => g.key === "Good")?.items.map((d) => d.host).sort()).toEqual(["dist1", "dist2"]);
  });
});
