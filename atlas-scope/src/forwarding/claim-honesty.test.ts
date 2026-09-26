/**
 * claim-honesty.test.ts — an outcome the engine does not rate as decided is never drawn as decided.
 *
 * Pins the 2026-09-21 critic's B1/B8 findings over the SHIPPED snapshot:
 *  - a "delivered" trace with a policy gap or an absence evidence item bands UNDETERMINED (card and
 *    hop), and its one-sentence claim names the gap;
 *  - a flow whose endpoints share one observed subnet is not routed through the SVI's ACLs;
 *  - the band rule is checked over a sweep, not only the two reported flows.
 */
import { describe, expect, it } from "vitest";
import { bandOfHopIn, bandOfTrace, claimBadge, isDecidedOutcome } from "../core/claims";
import type { Flow } from "../core/types";
import { isDefiniteDelivery, traceFlow, unobservedPolicyInputs } from "./engine";

type Protocol = Flow["protocol"];

const flow = (srcIp: string, dstIp: string, protocol: Protocol, dstPort: number | null): Flow => ({ srcIp, dstIp, protocol, srcPort: null, dstPort });

describe("an undecided delivery is not drawn as a resolved pass", () => {
  it("udp 10.0.30.10 → 10.0.10.7:53 (absence evidence) bands UNDETERMINED and names the gap", () => {
    const t = traceFlow(flow("10.0.30.10", "10.0.10.7", "udp", 53));
    expect(t.outcome).toBe("delivered");
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("INDETERMINATE");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.hops.map((h) => bandOfHopIn(h, t))).toEqual(["UNDETERMINED"]);
    expect(t.claim).toMatch(/not a decided pass/);
    expect(t.claim).toMatch(/binding not observed/);
  });

  it("tcp 10.0.20.50 → 10.0.10.50:443 at core2 (no ACLs collected) bands UNDETERMINED and names core2", () => {
    const t = traceFlow(flow("10.0.20.50", "10.0.10.50", "tcp", 443));
    expect(t.outcome).toBe("delivered");
    expect(unobservedPolicyInputs(t).map((g) => [g.host, g.kind])).toContainEqual(["core2", "acl-uncollected"]);
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(bandOfHopIn(t.hops[t.hops.length - 1]!, t)).toBe("UNDETERMINED");
    expect(t.claim).toMatch(/core2 holds a collected routing table but no collected ACLs/);
  });

  it("the flow once pinned as the definite delivery is router-originated, and is not RESOLVED", () => {
    /* REVERSED 2026-09-22 (auditor, B2). 10.0.30.1 is core1's own Vlan30 address; this test pinned it
       as the snapshot's definite delivery. A packet core1 originates arrives inbound on no interface,
       so it is refused, not walked. The RESOLVED-without-suffix branch is exercised on a host source in
       src/panels/decided-surfaces.counterfactual.test.tsx. */
    const t = traceFlow(flow("10.0.30.1", "10.0.20.10", "tcp", 443));
    expect(t.hops).toEqual([]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.claim).toMatch(/an address of core1 itself/);
  });

  it("a delivery resting on an FHRP ingress choice and an unobserved ingress port is not RESOLVED (critic B1)", () => {
    /* REVERSED 2026-09-21: tcp 10.0.10.50 -> 10.0.30.10:443 was pinned RESOLVED/SCOPED while its
       own caveat said core1 was ingress only by a point-in-time HSRP role ("traffic may enter via
       core2"). Traced from core2 it is dropped, and core2 holds no ACLs; and 8 core1 uplinks the
       source's frames could arrive by have no observed running configuration. */
    const t = traceFlow(flow("10.0.10.50", "10.0.30.10", "tcp", 443));
    expect(t.outcome).toBe("delivered");
    const kinds = unobservedPolicyInputs(t).map((g) => [g.host, g.kind]);
    expect(kinds).toContainEqual(["core2", "ingress-alternate"]);
    expect(kinds).toContainEqual(["core1", "ingress-port-unobserved"]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.claim).toMatch(/may instead enter via core2 \(HSRP Standby\)/);
    expect(t.claim).toMatch(/traced from core2 this flow is dropped/);
  });

  it("over a sweep, the trace band is RESOLVED/REFUTED only for decided outcomes, and a delivered claim names its gap exactly when it is not definite", () => {
    const ips = ["10.0.10.7", "10.0.10.50", "10.0.20.10", "10.0.20.50", "10.0.30.10", "10.0.30.20", "8.8.8.8", "192.168.1.1"];
    const services: [Protocol, number | null][] = [["tcp", 443], ["tcp", 22], ["udp", 53], ["icmp", null]];
    let undecidedDeliveries = 0;
    for (const s of ips)
      for (const d of ips)
        for (const [p, port] of services) {
          const t = traceFlow(flow(s, d, p, port));
          const band = bandOfTrace(t);
          if (band !== "UNDETERMINED") expect(isDecidedOutcome(t), JSON.stringify(t.flow)).toBe(true);
          if (t.outcome === "delivered") {
            const definite = isDefiniteDelivery(t);
            if (!definite) undecidedDeliveries += 1;
            expect(/not a decided pass/.test(t.claim), JSON.stringify(t.flow)).toBe(!definite);
            // No hop of an undecided delivery may band RESOLVED at the host that left it undecided.
            if (!definite) expect(t.hops.some((h) => bandOfHopIn(h, t) === "UNDETERMINED"), JSON.stringify(t.flow)).toBe(true);
          }
        }
    // The sweep must actually contain the case it guards, or it proves nothing.
    expect(undecidedDeliveries).toBeGreaterThan(0);
  });
});

describe("a flow inside one subnet is not modelled as routed", () => {
  it("tcp 10.0.30.10 → 10.0.30.20 is not a decided denial by PROTECT_SERVERS", () => {
    const t = traceFlow(flow("10.0.30.10", "10.0.30.20", "tcp", 443));
    expect(t.outcome).toBe("indeterminate");
    expect(t.hops).toEqual([]);
    expect(isDecidedOutcome(t)).toBe(false);
    expect(t.claim).toMatch(/both lie in 10\.0\.30\.0\/24/);
    expect(t.claim).toMatch(/bridged at L2/);
    expect(t.claim).not.toMatch(/PROTECT_SERVERS/);
  });

  it("udp and icmp 10.0.10.50 → 10.0.10.7 are not denied by INET_RETURN", () => {
    for (const [p, port] of [["udp", 53], ["icmp", null]] as [Protocol, number | null][]) {
      const t = traceFlow(flow("10.0.10.50", "10.0.10.7", p, port));
      expect(t.outcome, p).toBe("indeterminate");
      expect(t.claim, p).not.toMatch(/INET_RETURN/);
    }
  });

  it("a flow that does cross subnets is still routed", () => {
    expect(traceFlow(flow("10.0.30.10", "10.0.20.10", "tcp", 443)).hops.length).toBeGreaterThan(0);
  });
});
