/**
 * claims.ts over a fleet with NO collected routing table and NO collected ACL (disc-app-sample-assumptions #6).
 *
 * The reference sample always has some RIB and ACL hosts, so every sentence that joins those host lists read
 * well on it and nowhere else: with zero RIB hosts T4 said "(0 of 26 hosts have one: )" and the share payload
 * "RIBs collected for  (0 of 26 hosts)". Every host-list join in claims.ts now goes through the one owner,
 * `listPhrase` (src/core/phrases.ts), which always yields a phrase. This file runs the real claims module over
 * the real compiled fabric with its coverage lists emptied, so the empty case is executed, not assumed.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

vi.mock("./data", async (importOriginal) => {
  const real = await importOriginal<typeof import("./data")>();
  return {
    ...real,
    fabric: {
      ...real.fabric,
      coverage: { ...real.fabric.coverage, routableHosts: [], hostsWithRoutes: 0, aclHosts: [], hostsWithAcls: 0 },
    },
  };
});

import { T3_outOfScope, T4_unmodelledHost, sharePayload } from "./claims";
import { fabric } from "./data";
import type { Trace } from "./types";

/** The shapes an empty join leaves behind: a doubled space, a list introducer followed by nothing. */
function brokenJoins(s: string): string[] {
  const shapes: [string, RegExp][] = [
    ["double space", / {2,}/],
    ["colon then close", /:\s*[)."]/],
    ["'for' then nothing", /\bfor\s*[(.,]/],
    ["dangling comma", /,\s*[).]/],
  ];
  return shapes.filter(([, re]) => re.test(s)).map(([name]) => name);
}

const outOfScope: Trace = {
  flow: { srcIp: "198.51.100.7", dstIp: "203.0.113.9", protocol: "tcp", dstPort: 443, srcPort: null },
  outcome: "out-of-scope",
  hops: [],
  claim: "",
  caveats: [],
  unmodelledHosts: [],
  elapsedMs: 0,
};

describe("host-list sentences over a fleet with no collected RIB or ACL", () => {
  it("precondition: the mock really emptied the coverage lists the sentences join", () => {
    expect(fabric.coverage.routableHosts).toEqual([]);
    expect(fabric.coverage.aclHosts).toEqual([]);
    expect(fabric.devices.length).toBeGreaterThan(0);
  });

  it("T4 names that no host has a RIB instead of joining an empty list", () => {
    const s = T4_unmodelledHost("some-host");
    expect(brokenJoins(s), s).toEqual([]);
    expect(s).toContain(`(0 of ${fabric.devices.length} hosts have one: none)`);
  });

  it("the share payload's SCOPE line reads 'no host' for both empty lists", () => {
    const p = sharePayload(outOfScope);
    const scope = p.split("\n").find((l) => l.startsWith("SCOPE:"));
    expect(scope).toBeDefined();
    expect(brokenJoins(scope!), scope).toEqual([]);
    expect(scope).toBe(`SCOPE: RIBs collected for no host (0 of ${fabric.devices.length} hosts). ACLs collected for no host.`);
  });

  it("T3 says 'none recorded' when no subnet was observed", () => {
    const s = T3_outOfScope("198.51.100.7", []);
    expect(brokenJoins(s), s).toEqual([]);
    expect(s).toContain("Observed subnets: none recorded.");
  });
});

describe("the class: every name-list join in claims.ts goes through listPhrase", () => {
  /* A guard on the three sentences above would be a named subset standing in for the class. The class is
     "a list of names joined into prose", and its only spelling in this module is `.join(", ")` (the "; "
     joins separate CLAUSES, each of which is itself a phrase, and the "\n" join assembles lines). So the
     module may not contain that spelling at all, nor a hand-rolled `|| "no host"` fallback beside one. */
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "claims.ts"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
  it("claims.ts has no bare comma join and no local empty-list fallback", () => {
    expect(src.match(/\.join\(\s*["'`],\s*["'`]\s*\)/g) ?? []).toEqual([]);
    expect(src.match(/\|\|\s*["'`]no host["'`]/g) ?? []).toEqual([]);
  });
  it("and it does import the one owner", () => {
    expect(src).toMatch(/import \{[^}]*\blistPhrase\b[^}]*\} from "\.\/phrases";/);
  });
});
