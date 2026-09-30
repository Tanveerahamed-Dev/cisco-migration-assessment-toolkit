/**
 * engine.off-subnet.test.ts — B4: a source in no observed subnet is out of scope, AND the claim
 * says why, in the words the engine owns.
 *
 * The acceptance report (2026-09-23, B4) found the sentence "<ip> lies in no subnet this collection
 * observed — no SVI, connected route or endpoint record contains it" pinned by nothing: mutating it
 * left every test green, because the verdict, the badge and the other clauses carried the check.
 * The criterion is "returns out-of-scope, AND says so in words"; this pins the words.
 *
 * Off-subnet is decided HERE, independently of the engine, from the three kinds of record the
 * sentence names (SVI addresses, connected routes, endpoint records), so the sources are not chosen
 * by asking the function under test which ones it refuses.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import type { Flow } from "../core/types";
import { FLOW_PROTOCOLS, formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4, parsePrefix, prefixContains, protocolCarriesPorts, type Prefix } from "./ip";
import { refusalOf, suggestedFlows, traceFlow } from "./engine";
import { describeGolden } from "../test-support/golden-sample";
import { GOLDEN_FORWARDING as G } from "../test-support/golden-expectations";

/** Every prefix the collection observed: SVI subnets and connected routes. */
const OBSERVED: Prefix[] = [
  ...fabric.l3.flatMap((r) => {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    return a === null ? [] : [a.prefix];
  }),
  ...Object.values(fabric.routes).flatMap((rs) =>
    rs.filter((r) => r.source === "connected").flatMap((r) => {
      const p = parsePrefix(r.prefix);
      return p === null ? [] : [p];
    }),
  ),
];
const ENDPOINT_IPS = new Set(fabric.endpoints.map((e) => e.ip).filter((ip): ip is string => ip !== null));

const isOffSubnet = (ip: string): boolean => {
  const v = parseIpv4(ip);
  return v !== null && !OBSERVED.some((p) => prefixContains(p, v)) && !ENDPOINT_IPS.has(ip);
};

/** Fourteen sources spread over documentation, private, CGNAT, link-local and public space. */
const SOURCES = [
  "8.8.8.8",
  "1.1.1.1",
  "198.51.100.7",
  "203.0.113.9",
  "192.0.2.5",
  "192.168.1.1",
  "172.16.0.10",
  "100.64.0.10",
  "169.254.1.10",
  "11.0.0.10",
  "10.1.0.10",
  "10.0.50.10",
  "10.200.0.10",
  "45.33.32.156",
];

/** Destinations: every suggested flow's, and hosts inside every observed SVI subnet. */
function destinations(): string[] {
  const out = new Set<string>(suggestedFlows().map((s) => s.flow.dstIp));
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    const h = a === null ? null : hostAddressIn(a.prefix, 10);
    if (h !== null) out.add(formatIpv4(h));
  }
  return [...out].sort();
}

describe("B4: a source in no observed subnet is out of scope and the claim says so in words", () => {
  it("every source used here is off-subnet by the records the sentence names (precondition, checked independently)", () => {
    for (const s of SOURCES) expect(isOffSubnet(s), s).toBe(true);
    expect(new Set(SOURCES).size).toBe(14);
  });

  it("each (source, flow) is out-of-scope, consults no device, and carries the 'lies in no subnet' sentence", () => {
    const dsts = destinations();
    let traces = 0;
    for (const srcIp of SOURCES)
      for (const dstIp of dsts)
        for (const protocol of FLOW_PROTOCOLS)
          for (const dstPort of protocolCarriesPorts(protocol) ? [22, 443] : [null]) {
            const f: Flow = { srcIp, dstIp, protocol, dstPort, srcPort: null };
            const t = traceFlow(f);
            traces += 1;
            const where = JSON.stringify(f);
            expect(t.outcome, where).toBe("out-of-scope");
            expect(t.hops, where).toEqual([]);
            expect(refusalOf(t)?.kind, where).toBe("outside-observed-subnets");
            expect(t.claim, where).toContain(
              `${srcIp} lies in no subnet this collection observed — no SVI, connected route or endpoint record contains it`,
            );
            expect(t.claim, where).toContain("so no ingress device can be named and no forwarding claim is made");
          }
    expect(traces).toBe(SOURCES.length * dsts.length * (FLOW_PROTOCOLS.filter(protocolCarriesPorts).length * 2 + FLOW_PROTOCOLS.filter((p) => !protocolCarriesPorts(p)).length));
    /* UPDATED phase 3: the sweep's size was pinned as "> 500", a number measured on the old sample (its
       suggested flows then had more distinct destinations). What it guarded is that the destinations reach
       into EVERY observed SVI subnet, so that is asserted from the data; the exact count is the golden pin. */
    for (const r of fabric.l3) {
      const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
      if (a === null) continue;
      expect(dsts.some((d) => prefixContains(a.prefix, parseIpv4(d)!)), `a destination inside ${r.cite}'s subnet`).toBe(true);
    }
    expect(traces).toBeGreaterThan(SOURCES.length);
  });
});

describeGolden("B4 on the reference sample", () => {
  it("the off-subnet sweep's size", () => {
    const dsts = destinations();
    expect(SOURCES.length * dsts.length * (FLOW_PROTOCOLS.filter(protocolCarriesPorts).length * 2 + FLOW_PROTOCOLS.filter((p) => !protocolCarriesPorts(p)).length)).toBe(G.offSubnetTraces);
  });
});
