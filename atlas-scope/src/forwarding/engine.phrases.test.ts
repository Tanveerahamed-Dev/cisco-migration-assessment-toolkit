/**
 * engine.phrases.test.ts — every name list the engine joins into prose goes through the one owner,
 * `listPhrase` (src/core/phrases.ts), so an empty list reads "no host", never "of  only"
 * (disc-app-sample-assumptions #6).
 *
 * The reference sample always has RIB hosts, so SCOPE_PHRASE ("Under the collected RIBs of X and Y only")
 * and the base caveat ("Forwarding is modelled only from the RIBs collected for X, Y") read well on it and
 * nowhere else: with zero RIB hosts they read "Under the collected RIBs of  only (0 of 26 hosts…)". This
 * file runs the real engine over the real compiled fabric with its coverage host lists emptied, so the
 * empty case is executed, not assumed; and it holds the CLASS structurally — the module has no bare comma
 * or "and" join left, only `listPhrase` for names and `citeList` for citations.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

vi.mock("../core/data", async (importOriginal) => {
  const real = await importOriginal<typeof import("../core/data")>();
  return {
    ...real,
    fabric: {
      ...real.fabric,
      coverage: { ...real.fabric.coverage, routableHosts: [], hostsWithRoutes: 0 },
    },
  };
});

import { fabric } from "../core/data";
import { traceFlow } from "./engine";

/** The shapes an empty join leaves behind: a doubled space, a list introducer followed by nothing. */
function brokenJoins(s: string): string[] {
  const shapes: [string, RegExp][] = [
    ["double space", / {2,}/],
    ["'of' then nothing", /\bof\s+(only\b|[(.,])/],
    ["'for' then nothing", /\bfor\s*[(.,]/],
    ["dangling comma", /,\s*[).]/],
  ];
  return shapes.filter(([, re]) => re.test(s)).map(([name]) => name);
}

describe("the scope clause and the RIB caveat over a fleet with no collected RIB", () => {
  it("precondition: the mock really emptied the RIB host list the sentences join", () => {
    expect(fabric.coverage.routableHosts).toEqual([]);
    expect(fabric.devices.length).toBeGreaterThan(0);
  });

  it("the claim opens 'Under the collected RIBs of no host', and the RIB caveat names no host instead of an empty list", () => {
    /* A source outside every observed subnet: refused before any device is consulted, so the sentence is
       the scope clause plus the refusal, whatever the routes say. */
    const t = traceFlow({ srcIp: "198.51.100.7", dstIp: "203.0.113.9", protocol: "tcp", dstPort: 443, srcPort: null });
    expect(t.claim.startsWith(`Under the collected RIBs of no host (0 of ${fabric.devices.length} hosts in this topology)`), t.claim).toBe(true);
    expect(brokenJoins(t.claim), t.claim).toEqual([]);
    const rib = t.caveats.find((c) => c.startsWith("Forwarding is modelled only from the RIBs collected for"));
    expect(rib).toBeDefined();
    expect(rib).toContain("RIBs collected for no host (");
    expect(brokenJoins(rib!), rib).toEqual([]);
  });
});

describe("the class: every name-list join in engine.ts goes through listPhrase", () => {
  /* A guard on the two sentences above would be a named subset standing in for the class. The class is
     "a list joined into prose"; its spellings are `.join(", ")` and `.join(" and ")`. The module may use
     neither outside its one citation-list helper, nor a hand-rolled `|| "no host"` fallback. */
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "engine.ts"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
  const withoutCiteList = src.replace(/const citeList = \(cites: readonly string\[\]\): string => cites\.join\(", "\);/, "");

  it("engine.ts has exactly one comma join — the citation-list helper — and no 'and' join or local empty fallback", () => {
    expect(src.match(/\.join\(\s*["'`],\s*["'`]\s*\)/g) ?? [], "the citeList helper is the one comma join").toHaveLength(1);
    expect(withoutCiteList.match(/\.join\(\s*["'`],\s*["'`]\s*\)/g) ?? []).toEqual([]);
    expect(src.match(/\.join\(\s*["'`]\s*and\s*["'`]\s*\)/g) ?? []).toEqual([]);
    expect(src.match(/\|\|\s*["'`]no host["'`]/g) ?? []).toEqual([]);
  });

  it("and it does import the one owner", () => {
    expect(src).toMatch(/import \{[^}]*\blistPhrase\b[^}]*\} from "\.\.\/core\/phrases";/);
  });
});
