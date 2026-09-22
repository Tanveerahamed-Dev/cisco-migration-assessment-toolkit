/**
 * query.test.ts — the query engine measured against the REAL compiled fabric.
 *
 * Every expectation below is a number derived from `src/data/fabric.json` by independent
 * inspection (raw JSON traversal), not by re-running the engine's own code paths. A test that
 * recomputes an answer with the implementation's logic agrees with the implementation's bugs.
 *
 * The literals are therefore load-bearing: if the compiled snapshot changes, these fail loudly,
 * which is the correct outcome — the counts ARE the contract between the data and the UI.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "./data";
import type { Finding } from "./types";
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

/* Pinned from the snapshot at compile time; see the file header for why they are literals. */
const TOTAL_FINDINGS = 146;
const TOTAL_DEVICES = 26;
const HIGH_FINDINGS = 104;
const CRITICAL_FINDINGS = 3;
const MEDIUM_FINDINGS = 33;
const LOW_FINDINGS = 6;
const COMPOUND_RISK = 15;
const CORE1_FINDINGS = 32;
const ACCESS_ROLE_FINDINGS = 116;
const POOR_BAND_FINDINGS = 76;
const WITH_REMEDIATION = 66;
const UNCOLLECTED_DEVICES = 3;
const BRIDGE_TRUE_DEVICES = 19;
const BRIDGE_FALSE_DEVICES = 4;
const BRIDGE_UNKNOWN_DEVICES = 3;
const POOR_BAND_DEVICES = 12;
const DEVICES_WITH_CRITICAL = 12;

const ids = <T extends { id: string }>(xs: readonly T[]): string[] => xs.map((x) => x.id);

/** Independent restatement of the required tie-break, so the test does not borrow the engine's
 *  own comparator to check the engine's own comparator. `cite` is in the tuple because `id` is not
 *  an identity for every kind: 43 cross-layer rows in this snapshot share 5 ids. */
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

  it("reports a recognised key whose value is absent from this snapshot", () => {
    // `Info` is a legal Severity in the type contract but no finding in this snapshot carries it,
    // and `Fair` is a legal Band that no device carries. An empty result must be explainable.
    const p = parseQuery("severity:Info band:Fair");
    expect(p.unmatchableValues.map((u) => `${u.key}:${u.value}`)).toEqual([
      "severity:Info",
      "band:Fair",
    ]);
  });

  it("reports a key for which the snapshot observed no values at all", () => {
    // Every finding in this snapshot has wave === null. That is NOT 'no waves exist'; it is
    // 'migration waves were never observed', and the UI must be able to say so.
    const p = parseQuery("wave:2");
    expect(p.unobservedKeys).toContain("wave");
  });
});

describe("applyToFindings — each key returns a correct, non-empty subset", () => {
  const all = fabric.findings;

  it("filters by severity", () => {
    expect(applyToFindings(all, parseQuery("severity:Critical")).items).toHaveLength(
      CRITICAL_FINDINGS,
    );
    expect(applyToFindings(all, parseQuery("severity:High")).items).toHaveLength(HIGH_FINDINGS);
    expect(applyToFindings(all, parseQuery("severity:Medium")).items).toHaveLength(MEDIUM_FINDINGS);
    expect(applyToFindings(all, parseQuery("severity:Low")).items).toHaveLength(LOW_FINDINGS);
    expect(applyToFindings(all, parseQuery("severity:Critical,High")).items).toHaveLength(
      CRITICAL_FINDINGS + HIGH_FINDINGS,
    );
  });

  it("filters by category with a quoted multi-word value", () => {
    const r = applyToFindings(all, parseQuery('category:"Compound risk"'));
    expect(r.items).toHaveLength(COMPOUND_RISK);
    expect(r.items.every((f) => f.category === "Compound risk")).toBe(true);
  });

  it("filters by host through the finding's own device list", () => {
    const r = applyToFindings(all, parseQuery("host:core1"));
    expect(r.items).toHaveLength(CORE1_FINDINGS);
    expect(r.items.every((f) => f.devices.includes("core1"))).toBe(true);
  });

  it("filters by a device attribute the finding does not itself carry", () => {
    const byRole = applyToFindings(all, parseQuery("role:access"));
    expect(byRole.items).toHaveLength(ACCESS_ROLE_FINDINGS);
    expect(byRole.clauses[0]!.applicability).toBe("via-devices");

    const byBand = applyToFindings(all, parseQuery("band:Poor"));
    expect(byBand.items).toHaveLength(POOR_BAND_FINDINGS);
  });

  it("filters by field presence", () => {
    expect(applyToFindings(all, parseQuery("has:remediation")).items).toHaveLength(WITH_REMEDIATION);
    expect(applyToFindings(all, parseQuery("-has:remediation")).items).toHaveLength(
      TOTAL_FINDINGS - WITH_REMEDIATION,
    );
  });

  it("matches free text against title, detail and remediation", () => {
    const r = applyToFindings(all, parseQuery("gateway"));
    expect(r.items.length).toBe(27);
    const hay = (f: Finding) =>
      `${f.title} ${f.detail ?? ""} ${f.remediation ?? ""}`.toLowerCase();
    expect(r.items.every((f) => hay(f).includes("gateway"))).toBe(true);
  });

  it("ANDs multiple clauses with free text", () => {
    const r = applyToFindings(all, parseQuery("severity:High host:core1"));
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((f) => f.severity === "High" && f.devices.includes("core1"))).toBe(true);
    expect(r.items.length).toBeLessThan(Math.min(HIGH_FINDINGS, CORE1_FINDINGS));
  });
});

describe("negation excludes exactly what it should", () => {
  const all = fabric.findings;

  it("negates a determinate clause as the complement", () => {
    const pos = applyToFindings(all, parseQuery("severity:High")).items;
    const neg = applyToFindings(all, parseQuery("-severity:High")).items;
    expect(neg).toHaveLength(TOTAL_FINDINGS - HIGH_FINDINGS);
    const posIds = new Set(ids(pos));
    expect(neg.some((f) => posIds.has(f.id))).toBe(false);
    expect(pos.length + neg.length).toBe(TOTAL_FINDINGS);
  });

  it("does NOT sweep undetermined items into the negation — absence is not health", () => {
    // 19 devices touch at least one link the engine proved is a bridge; 4 touch only links it
    // proved are not; 3 touch links whose centrality was never computed. `-is:bridge` must return
    // the 4 proven-not, never the 3 unknown.
    const pos = applyToDevices(fabric.devices, parseQuery("is:bridge"));
    const neg = applyToDevices(fabric.devices, parseQuery("-is:bridge"));
    expect(pos.items).toHaveLength(BRIDGE_TRUE_DEVICES);
    expect(neg.items).toHaveLength(BRIDGE_FALSE_DEVICES);
    expect(pos.items.length + neg.items.length).toBe(TOTAL_DEVICES - BRIDGE_UNKNOWN_DEVICES);
    expect(neg.clauses[0]!.undetermined).toBe(BRIDGE_UNKNOWN_DEVICES);
  });
});

describe("an unrecognised key never silently passes everything through", () => {
  it("returns nothing and says why", () => {
    const r = applyToFindings(fabric.findings, parseQuery("frobnicate:yes"));
    expect(r.items).toHaveLength(0);
    expect(r.items.length).not.toBe(TOTAL_FINDINGS);
    const outcome = r.clauses[0]!;
    expect(outcome.applicability).toBe("unrecognised");
    expect(outcome.undetermined).toBe(TOTAL_FINDINGS);
    expect(outcome.excluded).toBe(0);
    expect(outcome.note).toMatch(/frobnicate/);
    expect(r.unrecognisedKeys).toEqual(["frobnicate"]);
  });

  it("does not let a recognised clause launder an unrecognised one", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:High frobnicate:yes"));
    expect(r.items).toHaveLength(0);
  });

  it("reports a key that cannot be evaluated on this entity rather than passing it", () => {
    // `layer` lives on cross-layer records. A punchlist finding cites `punchlist[n]` and carries no
    // link back to a cross_layer row, so the question is unanswerable for findings — and an
    // unanswerable question must not return a full, confident-looking list.
    const r = applyToFindings(fabric.findings, parseQuery("layer:L1+L3"));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.applicability).toBe("not-applicable");
    expect(r.clauses[0]!.undetermined).toBe(TOTAL_FINDINGS);

    const cl = applyToCrossLayer(fabric.crossLayer, parseQuery("layer:L1+L3"));
    expect(cl.items).toHaveLength(3);
    expect(cl.clauses[0]!.applicability).toBe("direct");
  });
});

describe("unobserved fields stay unobserved", () => {
  it("reports every finding as undetermined for wave, never as excluded", () => {
    const r = applyToFindings(fabric.findings, parseQuery("wave:2"));
    expect(r.items).toHaveLength(0);
    expect(r.clauses[0]!.undetermined).toBe(TOTAL_FINDINGS);
    expect(r.clauses[0]!.excluded).toBe(0);
    expect(r.clauses[0]!.note).toMatch(/not observed/i);
  });

  it("treats a finding with no device list as undetermined for device-derived clauses", () => {
    // F142 ('No QoS configured anywhere') names no device, so 'is this on an access switch?'
    // cannot be answered for it.
    const r = applyToFindings(fabric.findings, parseQuery("role:access"));
    expect(r.clauses[0]!.undetermined).toBe(1);
    expect(ids(r.items)).not.toContain("F142");
  });

  it("treats an uncollected device as undetermined for evidence-derived clauses", () => {
    const r = applyToDevices(fabric.devices, parseQuery("severity:Critical"));
    expect(r.items).toHaveLength(DEVICES_WITH_CRITICAL);
    expect(r.clauses[0]!.applicability).toBe("via-findings");
    expect(r.clauses[0]!.undetermined).toBe(UNCOLLECTED_DEVICES);
  });
});

describe("applyToDevices", () => {
  it("filters by direct device attributes", () => {
    expect(applyToDevices(fabric.devices, parseQuery("band:Poor")).items).toHaveLength(
      POOR_BAND_DEVICES,
    );
    expect(applyToDevices(fabric.devices, parseQuery("is:uncollected")).items).toHaveLength(
      UNCOLLECTED_DEVICES,
    );
    expect(applyToDevices(fabric.devices, parseQuery("tier:1")).items).toHaveLength(17);
    expect(applyToDevices(fabric.devices, parseQuery("platform:ios")).items).toHaveLength(22);
  });

  it("supports a trailing wildcard on an identifier value", () => {
    const r = applyToDevices(fabric.devices, parseQuery("host:access*"));
    expect(r.items).toHaveLength(17);
    expect(r.items.every((d) => d.host.startsWith("access"))).toBe(true);
  });
});

describe("per-clause exclusion accounting — the Grafana honesty property", () => {
  /* These assert VALUES derived from the raw snapshot, not shape invariants of the implementation.
     The earlier versions of this block checked `matched + excluded + undetermined === total`,
     `withoutThisClause >= items.length` and `items.length <= matched` — all three are tautologies
     of an implementation that assigns each row exactly one tri-state and ANDs the clauses, so they
     hold just as well when the tri-states themselves are wrong. */

  it("splits each clause's input the way the raw data splits it", () => {
    const r = applyToFindings(fabric.findings, parseQuery("host:core1"));
    // Derived by traversal: 32 findings name core1, F142 names no device at all (so the question is
    // unanswerable for it), and the remaining 113 name devices that are not core1.
    const naming = fabric.findings.filter((f) => f.devices.includes("core1")).length;
    const nameless = fabric.findings.filter((f) => f.devices.length === 0).length;
    expect([naming, nameless]).toEqual([32, 1]);
    const c = r.clauses[0]!;
    expect([c.matched, c.excluded, c.undetermined]).toEqual([32, 113, 1]);
  });

  it("reports what each clause alone costs the result set, as a number from the data", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:High host:core1"));
    // Dropping the severity gate leaves host:core1 (32 findings); dropping the host gate leaves
    // severity:High (104). Both are counted here from the raw records, not from the engine.
    expect(r.clauses[0]!.withoutThisClause).toBe(
      fabric.findings.filter((f) => f.devices.includes("core1")).length,
    );
    expect(r.clauses[1]!.withoutThisClause).toBe(
      fabric.findings.filter((f) => f.severity === "High").length,
    );
    expect(r.items).toHaveLength(
      fabric.findings.filter((f) => f.severity === "High" && f.devices.includes("core1")).length,
    );
  });

  it("counts free-text matches against the fields it claims to search", () => {
    const parsed = parseQuery("severity:High role:access has:remediation gateway");
    const r = applyToFindings(fabric.findings, parsed);
    expect(r.total).toBe(TOTAL_FINDINGS);
    const hay = (f: Finding) =>
      `${f.id} ${f.title} ${f.detail ?? ""} ${f.remediation ?? ""} ${f.category ?? ""} ${f.devices.join(" ")}`.toLowerCase();
    const matching = fabric.findings.filter((f) => hay(f).includes("gateway")).length;
    expect(matching).toBe(27);
    expect(r.textOutcome!.matched).toBe(matching);
    expect(r.textOutcome!.excluded).toBe(TOTAL_FINDINGS - matching);
    expect(r.clauses[0]!.matched).toBe(HIGH_FINDINGS);
    expect(r.clauses[0]!.excluded).toBe(TOTAL_FINDINGS - HIGH_FINDINGS);
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
    // Info is a legal Severity in the type contract, but this snapshot holds none — offering it
    // would invite a query that returns nothing for a reason the UI could not explain.
    expect(s.suggestions.map((x) => x.value)).toEqual(["Critical", "High", "Medium", "Low"]);
    const critical = s.suggestions.find((x) => x.value === "Critical")!;
    expect(critical.count).toBe(CRITICAL_FINDINGS);
  });

  it("offers real hosts and real bands, and no band the fleet does not have", () => {
    const hosts = suggest("host:", 5).suggestions.map((x) => x.value);
    const real = new Set(fabric.devices.map((d) => d.host));
    expect(hosts.length).toBeGreaterThan(0);
    expect(hosts.every((h) => real.has(h))).toBe(true);

    const bands = suggest("band:", 5).suggestions.map((x) => x.value);
    expect(bands).toContain("Poor");
    expect(bands).not.toContain("Fair");
  });

  it("filters value candidates by the prefix already typed", () => {
    const s = suggest("host:acc", 8);
    expect(s.suggestions.length).toBeGreaterThan(0);
    expect(s.suggestions.every((x) => x.value.toLowerCase().startsWith("acc"))).toBe(true);
    expect(s.replace).toEqual({ start: 5, end: 8 });
  });

  it("says plainly when a key has no observed values rather than showing an empty menu", () => {
    const s = suggest("wave:", 5);
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
    expect(valueDomain("category")!.map((d) => d.value)).toContain("Compound risk");
    expect(valueDomain("frobnicate")).toBeNull();
  });
});

describe("rankedSearch — one cross-entity search", () => {
  it("ranks the core1 DEVICE above findings that merely mention core1", () => {
    const r = rankedSearch("core1");
    expect(r.hits.length).toBeGreaterThan(0);
    const first = r.hits[0]!;
    expect(first.kind).toBe("device");
    expect(first.id).toBe("core1");

    const deviceScore = first.score;
    const findingHits = r.hits.filter((h) => h.kind === "finding");
    expect(findingHits.length).toBeGreaterThan(0);
    expect(findingHits.every((h) => h.score < deviceScore)).toBe(true);
    // The device is ranked first outright, not merely tied.
    expect(r.hits.filter((h) => h.score === deviceScore)).toHaveLength(1);
  });

  it("returns one hit per record, won by that record's strongest field", () => {
    // F003 names core1 in its device list AND in its title. It must appear once, credited to the
    // device list — a record that matches five of its own fields cannot flood the result list.
    // Identity is the row's citation, not its id: `id` repeats across cross-layer rows.
    const r = rankedSearch("core1", { limit: 500 });
    const keys = r.hits.map((h) => `${h.kind}|${h.cite}`);
    expect(new Set(keys).size).toBe(keys.length);
    const f003 = r.hits.find((h) => h.kind === "finding" && h.id === "F003");
    expect(f003).toBeDefined();
    expect(f003!.field).toBe("devices");
    expect(f003!.matchType).toBe("exact");
  });

  it("finds an exact finding id above anything that mentions it", () => {
    const r = rankedSearch("F001");
    expect(r.hits[0]).toMatchObject({ kind: "finding", id: "F001", matchType: "exact-id" });
  });

  it("names the field that matched and carries the citation", () => {
    const r = rankedSearch("10.0.10.50");
    const ep = r.hits.find((h) => h.kind === "endpoint");
    expect(ep).toBeDefined();
    expect(ep!.field).toBe("ip");
    expect(ep!.cite).toMatch(/^endpoint_identity\[/);
  });

  it("reaches interfaces and cross-layer records", () => {
    const kinds = new Set(rankedSearch("core1").hits.map((h) => h.kind));
    expect(kinds).toContain("interface");
    expect(kinds).toContain("cross-layer");
  });

  it("returns nothing (and says so) for a term present nowhere", () => {
    const r = rankedSearch("zzzz-not-in-the-snapshot");
    expect(r.hits).toHaveLength(0);
    expect(r.truncated).toBe(false);
    expect(r.totalHits).toBe(0);
  });

  it("is deterministic and stably tie-broken across repeated calls", () => {
    const a = rankedSearch("access");
    const b = rankedSearch("access");
    expect(a.hits.map((h) => `${h.kind}:${h.id}:${h.field}`)).toEqual(
      b.hits.map((h) => `${h.kind}:${h.id}:${h.field}`),
    );
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

  it("reports truncation instead of silently dropping hits", () => {
    const r = rankedSearch("access", { limit: 5 });
    expect(r.hits).toHaveLength(5);
    expect(r.truncated).toBe(true);
    expect(r.totalHits).toBeGreaterThan(5);
  });
});

describe("grouping and ordering", () => {
  it("groups findings by severity in severity order", () => {
    const groups = groupBy(fabric.findings, "severity");
    expect(groups.map((g) => g.key)).toEqual(["Critical", "High", "Medium", "Low"]);
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(TOTAL_FINDINGS);
    expect(groups[0]!.items).toHaveLength(CRITICAL_FINDINGS);
  });

  it("keeps an unobserved bucket separate and labelled, never folded into a value", () => {
    const groups = groupBy(fabric.findings, "wave");
    expect(groups).toHaveLength(1);
    expect(groups[0]!.observed).toBe(false);
    expect(groups[0]!.label).toMatch(/not observed/i);
    expect(groups[0]!.items).toHaveLength(TOTAL_FINDINGS);
  });

  it("groups devices by band in band order with the unobserved bucket last", () => {
    const groups = groupDevicesBy(fabric.devices, "band");
    expect(groups[groups.length - 1]!.observed).toBe(false);
    expect(groups[groups.length - 1]!.items).toHaveLength(UNCOLLECTED_DEVICES);
    const observed = groups.filter((g) => g.observed).map((g) => g.key);
    /* UPDATED 2026-09-22 (acceptance B1, second failure): the old expectation ["Excellent", "Good",
       "Poor", "Critical"] filed core2/dist1/dist2/podacc1/podacc2 under the PLAIN favourable bands,
       although every one of them is qualified (a scoring domain never assessed could not deduct) —
       that expectation pinned the defect. Band order is kept: each favourable band's qualified key
       sits directly after it, and this snapshot has no unqualified favourable band. */
    expect(observed).toEqual(["Excellent-partial", "Good-partial", "Poor", "Critical"]);
    expect(groups.find((g) => g.key === "Excellent-partial")?.label).toBe("Excellent (partial)");
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
      expect(firstNull).toBe(TOTAL_DEVICES - UNCOLLECTED_DEVICES);
      expect(list.slice(firstNull).every((d) => d.score === null)).toBe(true);
    }
    expect(asc[0]!.score).toBeLessThanOrEqual(asc[1]!.score!);
    expect(desc[0]!.score).toBeGreaterThanOrEqual(desc[1]!.score!);
  });

  it("applies secondary sort specs as tie-breaks", () => {
    const sorted = sortBy(fabric.findings, [
      { field: "severity", direction: "asc" },
      { field: "id", direction: "desc" },
    ]);
    const critical = sorted.filter((f) => f.severity === "Critical");
    expect(ids(critical)).toEqual(["F003", "F002", "F001"]);
  });

  it("preserves input order through filtering", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:High"));
    const expected = fabric.findings.filter((f) => f.severity === "High").map((f) => f.id);
    expect(ids(r.items)).toEqual(expected);
  });
});

describe("empty and degenerate input", () => {
  it("an empty query matches everything and says it is empty", () => {
    const p = parseQuery("   ");
    expect(p.isEmpty).toBe(true);
    const r = applyToFindings(fabric.findings, p);
    expect(r.items).toHaveLength(TOTAL_FINDINGS);
    expect(r.clauses).toHaveLength(0);
  });

  it("a bare key with no value is reported, not treated as free text", () => {
    const p = parseQuery("severity:");
    expect(p.clauses[0]!.values).toEqual([]);
    expect(p.clauses[0]!.incomplete).toBe(true);
    // An incomplete clause is not yet a filter; it must not empty the view while typing.
    const r = applyToFindings(fabric.findings, p);
    expect(r.items).toHaveLength(TOTAL_FINDINGS);
  });

  it("matching is case-insensitive on values but preserves the typed text in the clause", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:critical"));
    expect(r.items).toHaveLength(CRITICAL_FINDINGS);
    expect(parseQuery("severity:critical").clauses[0]!.values).toEqual(["critical"]);
  });
});

/* ────────────────────────────────────────────────────────────────────────────
 * Regression suite for the defects an adversarial refuter confirmed against this
 * engine. Each block states the defect it pins, and every expectation below is
 * derived by traversing `fabric.json` directly, never by re-running the code
 * path under test.
 * ──────────────────────────────────────────────────────────────────────────── */

/** Raw traversal helpers — deliberately independent of data.ts's indexes. */
const RAW_UNCOLLECTED = fabric.devices.filter((d) => !d.collected).map((d) => d.host);
const rawFindingsNaming = (pred: (host: string) => boolean): number =>
  fabric.findings.filter((f) => f.devices.some(pred)).length;
const rawHay = (f: Finding): string =>
  `${f.id} ${f.title} ${f.detail ?? ""} ${f.remediation ?? ""} ${f.category ?? ""} ${f.devices.join(" ")}`.toLowerCase();

describe("a never-collected device is an evidence gap, never an empty punchlist", () => {
  it("states the gap when every device the clause names was never collected", () => {
    // AP-floor1 is one of the three topology-only nodes. 0 findings name it — because nothing was
    // collected from it, not because it is clean. The result must carry that fact.
    expect(RAW_UNCOLLECTED).toContain("AP-floor1");
    expect(rawFindingsNaming((h) => h === "AP-floor1")).toBe(0);

    const r = applyToFindings(fabric.findings, parseQuery("host:AP-floor1"));
    expect(r.items).toHaveLength(0);
    const scope = r.clauses[0]!.scope;
    expect(scope.kind).toBe("device-scope");
    if (scope.kind !== "device-scope") throw new Error("unreachable");
    expect(scope.inScope).toBe(1);
    expect(scope.collectedInScope).toBe(0);
    expect(scope.evidenceBlind).toBe(true);
    expect(scope.uncollected.map((u) => u.host)).toEqual(["AP-floor1"]);
    // The claim carries its citation back into the snapshot.
    expect(scope.uncollected[0]!.cite).toBe("cable_map.nodes[host=AP-floor1]");
    expect(r.clauses[0]!.note).toMatch(/never collected/i);
    expect(r.clauses[0]!.note).toMatch(/AP-floor1/);
  });

  it("says the same thing on the cross-layer surface, which cannot contradict the finding surface", () => {
    const r = applyToCrossLayer(fabric.crossLayer, parseQuery("host:AP-floor1"));
    expect(r.items).toHaveLength(0);
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.evidenceBlind).toBe(true);
    expect(r.clauses[0]!.note).toMatch(/never collected/i);
  });

  it("is a property of the clause's device scope, not of a list of hostnames", () => {
    // `kind:ap` names no host at all, yet both APs it selects were never collected. A fix scoped to
    // the `host:` key would miss this; the honesty must come from the scope, not from a name list.
    const apHosts = fabric.devices.filter((d) => d.kind === "ap").map((d) => d.host);
    expect(apHosts).toHaveLength(2);
    expect(apHosts.every((h) => RAW_UNCOLLECTED.includes(h))).toBe(true);

    const r = applyToFindings(fabric.findings, parseQuery("kind:ap"));
    expect(r.items).toHaveLength(0);
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.evidenceBlind).toBe(true);
    expect(scope.uncollected.map((u) => u.host).sort()).toEqual([...apHosts].sort());
  });

  it("reports a PARTIAL gap without claiming the result is blind", () => {
    // tier 3 holds dist1, dist2 (collected) and AP-floor3-01, wan-edge-rtr1.lab (not). The five
    // findings that name a tier-3 device are real; the two silent devices are still a caveat.
    const tier3 = fabric.devices.filter((d) => d.tier === 3);
    expect(tier3).toHaveLength(4);
    expect(tier3.filter((d) => !d.collected)).toHaveLength(2);
    const expectedItems = rawFindingsNaming((h) => tier3.some((d) => d.host === h && d.collected));

    const r = applyToFindings(fabric.findings, parseQuery("tier:3"));
    expect(expectedItems).toBe(5);
    expect(r.items).toHaveLength(expectedItems);
    const scope = r.clauses[0]!.scope;
    if (scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    expect(scope.inScope).toBe(4);
    expect(scope.collectedInScope).toBe(2);
    expect(scope.evidenceBlind).toBe(false);
    expect(scope.uncollected).toHaveLength(2);
    expect(r.clauses[0]!.note).toMatch(/2 of 4/);
  });

  it("leaves a fully collected scope free of gap prose", () => {
    const r = applyToFindings(fabric.findings, parseQuery("host:core1"));
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

  it("carries the fleet-level coverage caveat on every evidence-derived result", () => {
    const r = applyToFindings(fabric.findings, parseQuery(""));
    expect(r.items).toHaveLength(TOTAL_FINDINGS);
    expect(r.evidenceScope.kind).toBe("fleet-partial");
    expect(r.evidenceScope.uncollected.map((u) => u.host).sort()).toEqual([...RAW_UNCOLLECTED].sort());
    expect(r.evidenceScope.uncollected.every((u) => u.cite.length > 0)).toBe(true);
    expect(r.evidenceScope.note).toMatch(/3 of 26/);

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
  it("excludes the rows that contain the term", () => {
    const expected = fabric.findings.filter((f) => !rawHay(f).includes("core1"));
    expect(expected).toHaveLength(TOTAL_FINDINGS - 32);

    const r = applyToFindings(fabric.findings, parseQuery("-core1"));
    expect(ids(r.items)).toEqual(expected.map((f) => f.id));
    expect(r.textOutcome!.terms).toEqual([]);
    expect(r.textOutcome!.excludedTerms).toEqual(["core1"]);
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

  it("combines with clauses", () => {
    const expected = fabric.findings.filter(
      (f) => f.severity === "High" && !rawHay(f).includes("core1"),
    );
    expect(expected).toHaveLength(88);
    expect(applyToFindings(fabric.findings, parseQuery("severity:High -core1")).items).toHaveLength(88);
  });

  it("never widens a negated term: a typo must not silently delete rows", () => {
    const r = applyToFindings(fabric.findings, parseQuery("-zzzznotpresent"));
    expect(r.items).toHaveLength(TOTAL_FINDINGS);
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

  it("does not claim a searchable value is unanswerable", () => {
    // 10.0.10.50 is a real endpoint IP; adding ":80" must not flip the palette's story about it.
    expect(rankedSearch("10.0.10.50", { limit: 500 }).totalHits).toBeGreaterThan(0);
    expect(suggest("10.0.10.50:80", 13).suggestions).toHaveLength(0);
    expect(suggest("10.0.10.50:80", 13).note).toMatch(/free text/i);
  });
});

describe("a clause in progress never empties the view", () => {
  it("treats an opening quote as a value not yet typed", () => {
    for (const input of ['severity:"', 'host:"', 'category:""']) {
      const p = parseQuery(input);
      expect(p.clauses[0]!.incomplete).toBe(true);
      expect(p.clauses[0]!.values).toEqual([]);
      expect(p.unmatchableValues).toEqual([]);
      expect(applyToFindings(fabric.findings, p).items).toHaveLength(TOTAL_FINDINGS);
    }
  });

  it("becomes a real filter as soon as the value is typed", () => {
    const p = parseQuery('category:"Compound risk"');
    expect(p.clauses[0]!.incomplete).toBe(false);
    expect(applyToFindings(fabric.findings, p).items).toHaveLength(COMPOUND_RISK);
  });
});

describe("result-level accounting cannot contradict the per-clause accounting", () => {
  it("never books an undecidable row as excluded", () => {
    const r = applyToFindings(fabric.findings, parseQuery("frobnicate:yes"));
    expect(r.excludedTotal).toBe(0);
    expect(r.undeterminedTotal).toBe(TOTAL_FINDINGS);
    expect(r.items.length + r.excludedTotal + r.undeterminedTotal).toBe(TOTAL_FINDINGS);
  });

  it("separates the decided-against rows from the undecided ones", () => {
    const r = applyToFindings(fabric.findings, parseQuery("host:AP-floor1"));
    // 145 findings name a device that is not AP-floor1 (decided); F142 names none (undecidable).
    expect(r.excludedTotal).toBe(145);
    expect(r.undeterminedTotal).toBe(1);
  });

  it("holds the three-way partition for a plain decidable clause", () => {
    const r = applyToFindings(fabric.findings, parseQuery("severity:High"));
    expect(r.excludedTotal).toBe(TOTAL_FINDINGS - HIGH_FINDINGS);
    expect(r.undeterminedTotal).toBe(0);
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
    expect(applyToFindings(fabric.findings, parseQuery("has:remediation")).items).toHaveLength(
      WITH_REMEDIATION,
    );
    expect(applyToDevices(fabric.devices, parseQuery("is:bridge")).items).toHaveLength(
      BRIDGE_TRUE_DEVICES,
    );
    expect(applyToDevices(fabric.devices, parseQuery("has:model")).items).toHaveLength(
      fabric.devices.filter((d) => d.model !== null).length,
    );
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
      // By cite, not by id: 43 cross-layer rows in this snapshot carry only 5 distinct ids.
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
    for (const term of ["core1", "access", "10.0.10.50", "F001", "gateway"]) {
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

  it("still reaches interfaces for a hostname search", () => {
    const kinds = new Set(rankedSearch("core1").hits.map((h) => h.kind));
    expect(kinds).toContain("interface");
  });
});

describe("a record is never swallowed by another that shares its id", () => {
  it("returns every cross-layer ROW that matches, not one per rule id", () => {
    // The compiler emits a cross-layer RULE id per host that trips the rule: 43 records, 5 ids.
    // Keying one-hit-per-record on the id therefore deletes real evidence from search results.
    const ids = new Set(fabric.crossLayer.map((c) => c.id));
    expect(fabric.crossLayer.length).toBe(43);
    expect(ids.size).toBe(5);

    const matches = fabric.crossLayer.filter((c) =>
      [c.id, ...c.hosts, c.layers, c.severity, c.title, c.detail, c.recommendation].some((v) =>
        (v ?? "").toLowerCase().includes("access"),
      ),
    );
    expect(matches).toHaveLength(35);

    const hits = rankedSearch("access", { limit: 2000 }).hits.filter((h) => h.kind === "cross-layer");
    expect(hits).toHaveLength(matches.length);
    expect(new Set(hits.map((h) => h.cite)).size).toBe(hits.length);
    expect(new Set(hits.map((h) => h.cite))).toEqual(new Set(matches.map((c) => c.cite)));
  });

  it("orders two records that share an id deterministically", () => {
    const a = rankedSearch("access", { limit: 2000 }).hits;
    const b = rankedSearch("access", { limit: 2000 }).hits;
    expect(a.map((h) => `${h.kind}:${h.cite}:${h.field}`)).toEqual(
      b.map((h) => `${h.kind}:${h.cite}:${h.field}`),
    );
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

  it("the fleet actually has such devices, so this test is not vacuous", () => {
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

  it('"-ios" specifically: the three topology-only devices are undecided, not admitted', () => {
    const r = applyToDevices(fabric.devices, parseQuery("-ios"));
    const admitted = r.items.filter((d) => !d.collected).map((d) => d.host);
    expect(admitted).toEqual([]);
    expect(r.undeterminedTotal).toBeGreaterThanOrEqual(3);
  });
});
