/**
 * query.band-qualification.test.ts — the query language answers band questions through the band
 * owner, so a favourable band that partly measures missing evidence is never a bare "yes"
 * (independent acceptance report 2026-09-22, B1: `is:healthy` returned core2, dist1, dist2,
 * podacc1 and podacc2 — all five qualified).
 *
 * The qualification rule is restated here from the per-host coverage owner
 * (`unassessedScoringDomains`), not read from `presentBand`, so the test is not the owner agreeing
 * with itself.
 */
import { describe, expect, it } from "vitest";
import { unassessedScoringDomains } from "./band-qualification";
import { fabric } from "./data";
import { applyToDevices, groupDevicesBy, parseQuery, sortDevicesBy, suggest } from "./query";
import type { Device } from "./types";

const AUDITED = ["core2", "dist1", "dist2", "podacc1", "podacc2"];
const FAVOURABLE = new Set(["Excellent", "Good"]);
const isQualified = (d: Device): boolean =>
  d.collected && d.band !== null && FAVOURABLE.has(d.band) && unassessedScoringDomains(d.host).length > 0;
const QUALIFIED = fabric.devices.filter(isQualified);
const byHost = (h: string): Device => fabric.devices.find((d) => d.host === h)!;

describe("band questions in the query language carry the qualification (B1)", () => {
  it("precondition: the five audited favourable-band hosts exist and every one is qualified", () => {
    for (const h of AUDITED) {
      const d = fabric.devices.find((x) => x.host === h);
      expect(d, h).toBeDefined();
      expect(isQualified(d!), `${h} is expected to be a qualified favourable band`).toBe(true);
    }
    expect(unassessedScoringDomains("podacc1")).toEqual(
      expect.arrayContaining(["protocol health (not assessed)", "routing (no RIB collected)", "ACLs (none collected)"]),
    );
  });

  it("is:healthy answers no qualified host with yes", () => {
    const r = applyToDevices(fabric.devices, parseQuery("is:healthy"));
    const yes = r.items.map((d) => d.host);
    for (const d of QUALIFIED) expect(yes, `${d.host} answered is:healthy with a bare yes`).not.toContain(d.host);
    expect(QUALIFIED.length).toBeGreaterThan(0);
  });

  it("-is:healthy does not turn the qualified hosts into a decided no either", () => {
    const r = applyToDevices(fabric.devices, parseQuery("-is:healthy"));
    const hits = r.items.map((d) => d.host);
    for (const d of QUALIFIED) expect(hits, d.host).not.toContain(d.host);
  });

  it("is:degraded cannot rule a qualified band out, so it is not a decided no (negation stays undecided)", () => {
    const neg = applyToDevices(fabric.devices, parseQuery("-is:degraded")).items.map((d) => d.host);
    for (const d of QUALIFIED) expect(neg, d.host).not.toContain(d.host);
  });

  it("band:excellent does not answer podacc1 with a bare yes; its qualified key does", () => {
    const plain = applyToDevices(fabric.devices, parseQuery("band:excellent")).items.map((d) => d.host);
    expect(plain).not.toContain("podacc1");
    const partial = applyToDevices(fabric.devices, parseQuery("band:excellent-partial")).items.map((d) => d.host);
    expect(partial).toContain("podacc1");
  });

  it("the band: vocabulary offers the qualified key, not the plain band, for the qualified hosts", () => {
    const vals = suggest("band:", 20).suggestions.map((s) => s.value);
    expect(vals).toContain("Excellent-partial");
    expect(vals).toContain("Good-partial");
    expect(vals).not.toContain("Excellent");
  });

  it("the host: row description for podacc1 states the band qualified and names the gaps", () => {
    const row = suggest("host:podacc1", 20).suggestions.find((s) => s.value === "podacc1");
    expect(row).toBeDefined();
    const detail = String((row as { detail?: unknown }).detail ?? "");
    expect(detail).toContain("partial");
    expect(detail).not.toMatch(/band Excellent(?!,)/);
    for (const g of unassessedScoringDomains("podacc1")) expect(detail).toContain(g.replace(/\s*\(.*$/, ""));
  });

  it("grouping by band files a qualified host under its qualified key, never the plain band", () => {
    const groups = groupDevicesBy(fabric.devices, "band");
    const plain = groups.find((g) => g.key === "Excellent");
    expect(plain?.items.map((d) => d.host) ?? []).not.toContain("podacc1");
    const partial = groups.find((g) => g.items.some((d) => d.host === "podacc1"));
    expect(partial?.label).toMatch(/partial/);
  });

  it("sorting by band never ties a qualified band with the plain band", () => {
    // An uncollected device has no unassessed domains to name, so its Excellent is plain. Its id
    // sorts AFTER podacc1's, so a tie (the defect) would fall back to identity and put podacc1 first.
    const plainExcellent: Device = { ...byHost("podacc1"), id: "zzz-plain", host: "zzz-plain", collected: false };
    const sorted = sortDevicesBy([byHost("podacc1"), plainExcellent], [{ field: "band", direction: "asc" }]);
    expect(sorted.map((d) => d.host)).toEqual(["zzz-plain", "podacc1"]);
  });
});
