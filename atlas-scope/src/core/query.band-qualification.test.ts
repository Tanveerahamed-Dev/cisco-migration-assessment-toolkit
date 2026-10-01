/**
 * query.band-qualification.test.ts — the query language answers band questions through the band
 * owner, so a favourable band that partly measures missing evidence is never a bare "yes"
 * (independent acceptance report 2026-09-22, B1: `is:healthy` returned core2, dist1, dist2,
 * podacc1 and podacc2 — all five qualified).
 *
 * The qualification rule is restated here from the per-host coverage owner
 * (`unassessedScoringDomains`), not read from `presentBand`, so the test is not the owner agreeing
 * with itself.
 *
 * TWO TIERS (src/test-support/golden-sample.ts). The audited host list is a fact about one snapshot: the
 * regenerated sample collected dist1's and dist2's RIB, ACLs and protocol health, so their Good is now PLAIN
 * (measured: unassessedScoringDomains("dist1") is empty) and the audited set is core2, podacc1 and podacc2. That
 * list lives in the golden block. Every other test is an invariant: its subjects are resolved by PROPERTY (the
 * qualified hosts of whatever fabric is loaded), and the device-list questions also carry one SYNTHETIC qualified
 * device (a host no coverage owner holds, so every scoring domain is unassessed), so the rule is exercised on a
 * dataset that happens to have no qualified host too.
 */
import { describe, expect, it } from "vitest";
import { describeGolden } from "../test-support/golden-sample";
import { unassessedScoringDomains } from "./band-qualification";
import { fabric } from "./data";
import { applyToDevices, applyToFindings, groupDevicesBy, parseQuery, sortDevicesBy, suggest } from "./query";
import type { Device } from "./types";

const FAVOURABLE = new Set(["Excellent", "Good"]);
const isQualified = (d: Device): boolean =>
  d.collected && d.band !== null && FAVOURABLE.has(d.band) && unassessedScoringDomains(d.host).length > 0;
/** A collected Excellent device on a host no coverage owner knows: qualified on any dataset. */
const SYNTHETIC: Device = {
  ...fabric.devices[0]!,
  id: "synthetic-qualified",
  host: "synthetic-qualified",
  collected: true,
  band: "Excellent",
};
const DEVICES: Device[] = [...fabric.devices, SYNTHETIC];
/** Qualified hosts of the loaded fabric (the vocabulary and host rows are built from the real fabric only). */
const REAL_QUALIFIED = fabric.devices.filter(isQualified);
/** ...and with the synthetic one, for the device-list questions. Never empty. */
const QUALIFIED = DEVICES.filter(isQualified);
/** The real subject for a host-row question: the qualified device with the most unassessed domains. */
const SUBJECT: Device | undefined = [...REAL_QUALIFIED].sort(
  (a, b) => unassessedScoringDomains(b.host).length - unassessedScoringDomains(a.host).length || a.host.localeCompare(b.host),
)[0];

describe("band questions in the query language carry the qualification (B1)", () => {
  it("precondition: the synthetic device is qualified, with every scoring domain unassessed", () => {
    expect(isQualified(SYNTHETIC)).toBe(true);
    expect(unassessedScoringDomains(SYNTHETIC.host)).toEqual([
      "protocol health (not assessed)",
      "routing (no RIB collected)",
      "ACLs (none collected)",
      "interfaces (no records)",
    ]);
  });

  it("is:healthy answers no qualified host with yes", () => {
    const r = applyToDevices(DEVICES, parseQuery("is:healthy"));
    const yes = r.items.map((d) => d.host);
    for (const d of QUALIFIED) expect(yes, `${d.host} answered is:healthy with a bare yes`).not.toContain(d.host);
    expect(QUALIFIED.length).toBeGreaterThan(0);
  });

  it("-is:healthy does not turn the qualified hosts into a decided no either", () => {
    const r = applyToDevices(DEVICES, parseQuery("-is:healthy"));
    const hits = r.items.map((d) => d.host);
    for (const d of QUALIFIED) expect(hits, d.host).not.toContain(d.host);
  });

  it("is:degraded cannot rule a qualified band out, so it is not a decided no (negation stays undecided)", () => {
    const neg = applyToDevices(DEVICES, parseQuery("-is:degraded")).items.map((d) => d.host);
    for (const d of QUALIFIED) expect(neg, d.host).not.toContain(d.host);
  });

  it("band:<band> does not answer a qualified host with a bare yes; its qualified key does", () => {
    for (const d of QUALIFIED) {
      const band = d.band!.toLowerCase();
      const plain = applyToDevices(DEVICES, parseQuery(`band:${band}`)).items.map((x) => x.host);
      expect(plain, `band:${band}`).not.toContain(d.host);
      const partial = applyToDevices(DEVICES, parseQuery(`band:${band}-partial`)).items.map((x) => x.host);
      expect(partial, `band:${band}-partial`).toContain(d.host);
    }
  });

  it("the band: vocabulary offers the qualified key for qualified hosts, and the plain band only where a plain one exists", () => {
    const vals = new Set(suggest("band:", 20).suggestions.map((s) => s.value));
    const collected = fabric.devices.filter((d) => d.collected && d.band !== null && FAVOURABLE.has(d.band));
    const expected = new Set(collected.map((d) => (isQualified(d) ? `${d.band}-partial` : d.band!)));
    const offered = [...vals].filter((v) => FAVOURABLE.has(v.replace(/-partial$/, ""))).sort();
    expect(offered).toEqual([...expected].sort());
  });

  it.runIf(SUBJECT !== undefined)("the host: row description for a qualified host states the band qualified and names the gaps", () => {
    const h = SUBJECT!.host;
    const row = suggest(`host:${h}`, 20).suggestions.find((s) => s.value === h);
    expect(row).toBeDefined();
    const detail = String((row as { detail?: unknown }).detail ?? "");
    expect(detail).toContain("partial");
    expect(detail).not.toMatch(new RegExp(`band ${SUBJECT!.band}(?!,)`));
    for (const g of unassessedScoringDomains(h)) expect(detail).toContain(g.replace(/\s*\(.*$/, ""));
  });

  it("grouping by band files a qualified host under its qualified key, never the plain band", () => {
    const groups = groupDevicesBy(DEVICES, "band");
    for (const d of QUALIFIED) {
      const plain = groups.find((g) => g.key === d.band);
      expect(plain?.items.map((x) => x.host) ?? [], d.host).not.toContain(d.host);
      const partial = groups.find((g) => g.items.some((x) => x.host === d.host));
      expect(partial?.label, d.host).toMatch(/partial/);
    }
  });

  it("sorting by band never ties a qualified band with the plain band", () => {
    // An uncollected device has no unassessed domains to name, so its Excellent is plain. Its id
    // sorts AFTER the qualified one's, so a tie (the defect) would fall back to identity and put it first.
    const plainExcellent: Device = { ...SYNTHETIC, id: "zzz-plain", host: "zzz-plain", collected: false };
    expect(isQualified(plainExcellent)).toBe(false);
    const sorted = sortDevicesBy([SYNTHETIC, plainExcellent], [{ field: "band", direction: "asc" }]);
    expect(sorted.map((d) => d.host)).toEqual(["zzz-plain", SYNTHETIC.host]);
  });

  it("the is:healthy note over findings says WHY rows are undecided, and does not call the undecided hosts non-matching", () => {
    /* MEASURED (running app, 2026-09-22): the finding view's note for is:healthy read "14 of 146
       name no device the fleet knows, so they are undetermined. No device in this fleet matches
       "is:healthy", so no findings could match it either." Only ONE finding (F142) names no
       device; the other 13 name a qualified host whose own answer is undecided, and "no device
       matches" read as "no device is healthy" while five hosts are undecided, not decided no. */
    const hosts = new Set(fabric.devices.map((d) => d.host));
    const namesNone = fabric.findings.filter((f) => f.devices.every((h) => !hosts.has(h))).length;
    const r = applyToFindings(fabric.findings, parseQuery("is:healthy"));
    const c = r.clauses[0]!;
    const note = c.note ?? "";
    expect(c.undetermined, "precondition: more findings are undecided than name no device").toBeGreaterThan(namesNone);
    const m = /(\d+) of \d+ name no device the fleet knows/.exec(note);
    expect(m?.[1], `the note's "name no device" count: ${note}`).toBe(String(namesNone));
    // The rest are attributed to the devices' own undecided answer, with the count stated.
    expect(note).toContain(`${c.undetermined - namesNone} of ${r.total}`);
    expect(note).toMatch(/itself undecided/);
    // And the scope does not say "no device matches" as if every host were decided against.
    expect(note).not.toMatch(/No device in this fleet matches/);
    /* The undecided devices, restated independently: every qualified favourable band, plus every
       device with no band observed at all — and nothing else. Counted in words in the note (the
       host list itself is bounded by the note's own rule); the structured scope carries them all. */
    if (c.scope.kind !== "device-scope") throw new Error("expected a device-scoped clause");
    const expected = fabric.devices.filter((d) => isQualified(d) || d.band === null).map((d) => d.host).sort();
    expect(c.scope.undecided.map((x) => x.host).sort()).toEqual(expected);
    for (const d of REAL_QUALIFIED) expect(expected).toContain(d.host);
    expect(note).toContain(`${expected.length} devices are undecided`);
  });
});

describeGolden("band qualification on the reference sample", () => {
  it("the audited qualified favourable bands are core2, podacc1 and podacc2; dist1 and dist2 are plain Good", () => {
    expect(REAL_QUALIFIED.map((d) => d.host).sort()).toEqual(["core2", "podacc1", "podacc2"]);
    for (const h of ["dist1", "dist2"]) {
      const d = fabric.devices.find((x) => x.host === h)!;
      expect(d.band).toBe("Good");
      expect(unassessedScoringDomains(h), h).toEqual([]);
    }
    expect(unassessedScoringDomains("podacc1")).toEqual(
      expect.arrayContaining(["protocol health (not assessed)", "routing (no RIB collected)", "ACLs (none collected)"]),
    );
    // The host-row test above ran on a real subject here (it is skipped by name only where none exists).
    expect(SUBJECT?.host).toBe("podacc1");
  });

  it("the band: vocabulary offers Excellent-partial, Good-partial and plain Good, and no plain Excellent", () => {
    const vals = suggest("band:", 20).suggestions.map((s) => s.value);
    expect(vals).toEqual(expect.arrayContaining(["Excellent-partial", "Good-partial", "Good"]));
    expect(vals).not.toContain("Excellent");
  });
});
