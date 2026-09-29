/**
 * dataset.example-query.test.ts — the query bar's example returns rows on WHATEVER dataset is loaded.
 *
 * The header teaches the query grammar with an example built from the loaded snapshot (Header.tsx
 * `exampleQuery`), and submitting the bar opens the findings surface. An example whose every literal
 * exists but whose clauses never co-occur — a severity that has findings, AND a host that has none of
 * them — is an empty result: it sends the reader to "no rows" and teaches them the tool is broken. That
 * is what the example did when it paired the highest severity with the first routable host, which on a
 * real fleet is usually a core router with no finding of that severity.
 *
 * The property is checked by RUNNING the example through the query engine the findings surface uses
 * (core/query.ts `applyToFindings`), on the bundled dataset and on datasets installed at run time.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CompiledDataset } from "./dataset/types";
import { asOpenedFile, compileGolden } from "./dataset/testing";

afterEach(() => {
  vi.resetModules();
});

async function exampleOn(set: CompiledDataset | null): Promise<{ example: string; rows: number; findings: number }> {
  if (set !== null) (await import("./dataset/slot")).installDataset(asOpenedFile(set));
  const { exampleQuery } = await import("../app/Header");
  const { applyToFindings, parseQuery } = await import("./query");
  const { fabric } = await import("./data");
  const example = exampleQuery();
  return { example, rows: applyToFindings(fabric.findings, parseQuery(example)).items.length, findings: fabric.findings.length };
}

/** The same fleet with every finding at one severity dropped from one host — still a real, compiled fabric. */
function withoutHostFindings(set: CompiledDataset, host: string): CompiledDataset {
  const c = structuredClone(set);
  c.fabric.findings = c.fabric.findings.filter((f) => !f.devices.includes(host));
  return c;
}

describe("the header's example query returns rows on the loaded dataset", () => {
  it("on the bundled dataset", async () => {
    const r = await exampleOn(null);
    expect(r.findings, "the dataset has findings to return").toBeGreaterThan(0);
    expect(r.rows, `"${r.example}" returns no findings`).toBeGreaterThan(0);
  });

  it("on the engine's golden snapshot, installed at run time", async () => {
    const r = await exampleOn(compileGolden());
    expect(r.findings).toBeGreaterThan(0);
    expect(r.rows, `"${r.example}" returns no findings`).toBeGreaterThan(0);
  });

  it("when the first routable host carries no finding at all", async () => {
    const golden = compileGolden();
    const first = golden.fabric.coverage.routableHosts[0];
    expect(first, "the golden fleet has a routable host (precondition)").toBeDefined();
    const r = await exampleOn(withoutHostFindings(golden, first!));
    expect(r.findings).toBeGreaterThan(0);
    expect(r.rows, `"${r.example}" returns no findings`).toBeGreaterThan(0);
  });
});
