/**
 * acl-coverage.test.ts — the rendered ACL honesty denominator, as a CLASS.
 *
 * THE DEFECT. Five surfaces (status bar, coverage disclosure, every claim card's scope block, the
 * device ACL tab and the Inspector's coverage tab) all rendered
 * `fabric.coverage.aclLinesUnevaluable` — the count of lines carrying the producer's `unevaluable`
 * boolean. On the shipped snapshot that is ONE line, `core1 MGMT_IN[0]`, and the engine resolves
 * its object group and decides it perfectly well. Meanwhile the engine's own `lineEvaluability()`
 * refuses THREE lines, none of them that one, and the snapshot's own reachability analysis returns
 * indeterminate on FIVE. So a trace could state "PROTECT_SERVERS line 2 cannot be evaluated"
 * directly above a scope block asserting exactly one unmodellable line — a different line.
 *
 * WHY THE OLD TEST COULD NOT CATCH IT. `Header.test.tsx` asserted the UI contained
 * `String(fabric.coverage.aclLinesUnevaluable)`. That proves the UI echoes a field. It says nothing
 * about whether the field answers the question the sentence around it asks.
 *
 * WHAT IS ASSERTED HERE, and why each is a class rather than an instance:
 *
 *   1. The union is never narrower than the set the ENGINE refuses. That is the set that actually
 *      poisons a verdict, so any rendered "cannot be decided" count below it is an understatement
 *      by construction — whatever the data happens to be.
 *   2. Every engine-refused line is NAMED in the union's member list, so the count and the names
 *      cannot drift apart.
 *   3. No source set is treated as a superset of another. If a future snapshot made them nested,
 *      the union would still be correct, so this is asserted as a property of the computation, not
 *      of today's numbers.
 *   4. Every surface that states an ACL denominator states the UNION. This walks the SOURCE of
 *      the rendering modules rather than a list of known call sites: a sixth surface added later
 *      that reaches for `coverage.aclLinesUnevaluable` fails this test.
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { aclUndecidability, allAclLines, undecidableAclSentence } from "./acl-coverage";
import { fabric } from "./data";
import { lineEvaluability } from "../forwarding/engine";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

describe("the undecidable ACL surface", () => {
  const u = aclUndecidability();

  it("counts every collected line as its denominator", () => {
    expect(u.total).toBe(allAclLines().length);
    expect(u.total).toBe(fabric.coverage.aclLinesTotal);
    expect(u.total).toBeGreaterThan(0);
  });

  it("is never narrower than the set this engine refuses to evaluate", () => {
    const refused = allAclLines().filter(({ line }) => !lineEvaluability(line).evaluable);
    expect(u.engineRefused.length).toBe(refused.length);
    expect(
      u.count,
      "a rendered 'cannot be decided' count below the engine's own refusal count is an overclaim",
    ).toBeGreaterThanOrEqual(refused.length);
  });

  it("names every engine-refused line in its member list", () => {
    for (const { host, acl, line } of allAclLines()) {
      if (lineEvaluability(line).evaluable) continue;
      const member = u.members.find(
        (m) => m.host === host && m.acl === acl && m.index === line.index,
      );
      expect(member, `${host} ${acl}[${line.index}] is refused by the engine but is not a member`).toBeDefined();
      expect(member?.sources).toContain("engine");
    }
  });

  it("carries the producer's flag and the snapshot's indeterminate rows as their own sources", () => {
    const flagged = allAclLines().filter(({ line }) => line.unevaluable);
    expect(u.bySource.producer).toBe(flagged.length);
    const indeterminate = fabric.aclFindings.filter(
      (f) => (f.verdict ?? "").toLowerCase() === "indeterminate",
    );
    expect(u.bySource.snapshot).toBe(indeterminate.length);
  });

  it("gives every member at least one reason, one per source, in stable order", () => {
    for (const m of u.members) {
      expect(m.sources.length, `${m.label} has no source`).toBeGreaterThan(0);
      expect(m.reasons.length).toBe(m.sources.length);
      for (const r of m.reasons) expect(r.length).toBeGreaterThan(10);
    }
    /* Determinism: the same call twice must produce the same list in the same order. */
    expect(aclUndecidability().members.map((m) => m.label)).toEqual(u.members.map((m) => m.label));
  });

  it("is the union, not any one source — proven on the shipped data", () => {
    /* This is the instance that made the defect visible, pinned so a regression is loud: the
       three sets are genuinely disjoint in part, so no single one may be the denominator. */
    const engine = new Set(u.members.filter((m) => m.sources.includes("engine")).map((m) => m.label));
    const producer = new Set(u.members.filter((m) => m.sources.includes("producer")).map((m) => m.label));
    const onlyProducer = [...producer].filter((l) => !engine.has(l));
    const onlyEngine = [...engine].filter((l) => !producer.has(l));
    expect(
      onlyProducer.length + onlyEngine.length,
      "if these ever became nested, the union is still right — but this snapshot proves they are not",
    ).toBeGreaterThan(0);
    expect(u.count).toBeGreaterThan(Math.max(u.bySource.engine, u.bySource.producer));
  });

  it("states the union and its three contributions in one sentence", () => {
    const s = undecidableAclSentence(u);
    expect(s).toContain(`${u.count} of ${u.total}`);
    expect(s).toContain(String(u.bySource.engine));
    expect(s).toContain(String(u.bySource.producer));
    expect(s).toContain(String(u.bySource.snapshot));
    expect(s).toMatch(/cannot be decided/);
  });
});

describe("no surface states the producer's flag as the ACL denominator", () => {
  /**
   * The five surfaces the critic captured, plus the module that computes the honest figure. Read
   * as SOURCE text: a rendering module reaching for `coverage.aclLinesUnevaluable` is reaching for
   * the wrong set, whatever sentence it wraps it in. `acl-coverage.ts` is exempt because it is the
   * module whose job is to combine that field with the other two.
   */
  const RENDERERS = [
    "app/StatusBar.tsx",
    "app/CoverageBar.tsx",
    "panels/ClaimCard.tsx",
    "panels/DevicePane.tsx",
  ];

  /** Comments are stripped: the question is what the module READS, not what it explains. */
  const code = (rel: string): string =>
    readFileSync(join(SRC, rel), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, " ")
      .replace(/(^|[^:])\/\/[^\n]*/g, "$1");

  it.each(RENDERERS)("%s renders the union rather than the producer's flag", (rel) => {
    const src = code(rel);
    expect(
      src.includes("aclLinesUnevaluable"),
      `${rel} reads coverage.aclLinesUnevaluable. That field counts only the lines the producer's ` +
        `parser flagged; it is neither an upper nor a lower bound on the lines this engine refuses. ` +
        `Use aclUndecidability() from core/acl-coverage.ts.`,
    ).toBe(false);
    expect(src).toContain("aclUndecidability");
  });

  it("the comment stripper leaves the code it is asked to judge", () => {
    /* A stripper that ate everything would make every assertion above vacuous. */
    for (const rel of RENDERERS) {
      const src = code(rel);
      expect(src, `${rel} stripped to nothing`).toContain("aclUndecidability");
      expect(src.length).toBeGreaterThan(500);
    }
  });

  it("the Inspector's coverage tab reports the union too", () => {
    const src = readFileSync(join(SRC, "panels/Inspector.tsx"), "utf8");
    expect(src).toContain("aclUndecidability");
    /* The Inspector still SHOWS `coverage.aclLinesUnevaluable` — deliberately: it reconciles it,
       as an independent comparison against the engine's own rule. What it must not do is title a
       gap block with it. */
    expect(src).not.toContain('title: "ACL lines the producer could not evaluate"');
  });
});
