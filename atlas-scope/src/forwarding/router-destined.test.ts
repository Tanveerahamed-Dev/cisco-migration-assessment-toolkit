/**
 * router-destined.test.ts — traffic ADDRESSED TO a router is received by it, not forwarded out of
 * the interface that owns the address (acceptance B8, 2026-09-22 independent acceptance report).
 *
 * The defect: 10.0.10.50 → 10.0.30.1 (core1's own Vlan30 address) was "denied" on tcp/3389 and
 * "delivered" on tcp/22 by PROTECT_SERVERS, a list bound OUTBOUND on core1 Vlan30. On IOS a packet
 * addressed to the router's own interface is punted to the router, never switched out of Vlan30, so
 * an outbound interface ACL does not decide it. The engine already refused router-owned SOURCES; it
 * had no matching rule for router-owned DESTINATIONS, and the one counterexample the product ever
 * offered on real data (tcp/22 "delivered" beside the tcp/3389 denial) rested on that error.
 *
 * The class, not a list: the owned addresses below are derived here, independently of the engine's
 * own index, from every collected interface address — SVI addresses, FHRP virtual addresses and RIB
 * `local` /32s. Every flow toward one of them, from sources in every observed subnet, is checked.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import type { Flow, Trace } from "../core/types";
import { counterexample, traceFlow } from "./engine";

const tcp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });

/** host -> the addresses its collected interfaces own. */
function ownedAddresses(): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>();
  const add = (ip: string, host: string): void => {
    const set = m.get(ip) ?? new Set<string>();
    set.add(host);
    m.set(ip, set);
  };
  for (const r of fabric.l3) {
    if (r.host === null || r.sviIp === null) continue;
    add(r.sviIp.split(/[ /]/)[0]!, r.host);
    if (r.vip !== null) add(r.vip, r.host);
  }
  for (const [host, routes] of Object.entries(fabric.routes)) {
    for (const r of routes) if (r.source === "local" && r.prefix.endsWith("/32")) add(r.prefix.slice(0, -3), host);
  }
  return m;
}

const OWNED = ownedAddresses();
const SOURCES = ["10.0.10.50", "10.0.20.10", "10.0.30.5", "10.0.40.50"];
const PROBES: ReadonlyArray<[Flow["protocol"], number | null]> = [["tcp", 22], ["tcp", 443], ["tcp", 3389], ["udp", 53], ["udp", 161], ["icmp", null]];

/**
 * A denial decided by an outbound list AT A DEVICE THAT OWNS THE DESTINATION. An outbound list at a
 * device the packet merely transits (10.0.40.2 reached through core1's static 10.0.0.0/16 out of
 * Vlan30) is a real filter and stays decided; only the owner receives the packet instead of
 * switching it out of an interface.
 */
const outboundDecidedAtOwner = (t: Trace): boolean => {
  const owners = OWNED.get(t.flow.dstIp) ?? new Set<string>();
  const last = t.hops[t.hops.length - 1];
  return last !== undefined && last.verdict === "denied" && owners.has(last.host) && /applied outbound/.test(t.claim);
};

describe("B8: traffic addressed to a router's own interface is not decided by an outbound interface ACL", () => {
  it("the class is non-empty and includes the address the defect was found on", () => {
    expect(OWNED.size, "precondition: collected interface addresses exist").toBeGreaterThan(5);
    expect([...(OWNED.get("10.0.30.1") ?? [])]).toEqual(["core1"]);
  });

  it("10.0.10.50 → 10.0.30.1 tcp/3389 is not a PROTECT_SERVERS denial: it is undecided, and says why", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.1", 3389));
    expect(t.hops.length).toBeGreaterThan(0);
    expect(t.outcome).toBe("indeterminate");
    expect(t.hops.flatMap((h) => (h.decidedBy === null ? [] : [h.decidedBy.cite]))).not.toContain("acls.core1.PROTECT_SERVERS[3]");
    const last = t.hops[t.hops.length - 1]!;
    expect(last.host).toBe("core1");
    expect(last.verdict).toBe("unmodeled");
    expect(last.outIntf).toBeNull();
    // What is and is not modelled, in the verdict itself.
    expect(t.claim).toMatch(/received by core1/);
    expect(t.claim).toMatch(/outbound interface ACL does not/);
    expect(t.claim).toMatch(/control-plane/);
    expect(t.claim).toMatch(/not modelled/);
  });

  it("…and tcp/22 to the same address is not 'delivered' on the strength of that outbound list either", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.1", 22));
    expect(t.outcome).toBe("indeterminate");
    expect(JSON.stringify(t.hops.map((h) => h.decidedBy))).not.toMatch(/PROTECT_SERVERS/);
  });

  it("no flow toward any collected interface address is delivered, or refused by an outbound list at its owner", () => {
    let checked = 0;
    const bad: string[] = [];
    for (const dst of OWNED.keys())
      for (const src of SOURCES)
        for (const [protocol, dstPort] of PROBES) {
          if (src === dst) continue;
          const t = traceFlow({ srcIp: src, dstIp: dst, protocol, dstPort, srcPort: null });
          if (t.hops.length === 0) continue; // refused before any device: intra-subnet etc., its own rule
          checked += 1;
          const label = `${protocol}/${dstPort ?? "-"} ${src} -> ${dst}: ${t.outcome}`;
          if (t.outcome === "delivered") bad.push(`${label} (delivered to a router's own address)`);
          if (t.outcome === "denied" && outboundDecidedAtOwner(t)) bad.push(`${label} (${t.claim})`);
        }
    expect(checked, "precondition: flows toward owned addresses reached a device").toBeGreaterThan(20);
    expect(bad).toEqual([]);
  });

  it("control: TRANSIT traffic through the same interface is still decided by the outbound list", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.10", 3389));
    expect(t.outcome).toBe("denied");
    expect(t.hops[0]!.decidedBy?.cite).toBe("acls.core1.PROTECT_SERVERS[3]");
    expect(t.claim).toMatch(/applied outbound on core1 Vlan30/);
  });

  it("the near-miss that rested on the misattribution is no longer offered", () => {
    const f = tcp("10.0.10.50", "10.0.30.1", 3389);
    const cx = counterexample(f, traceFlow(f));
    expect(cx.found).toBe(false);
  });
});
