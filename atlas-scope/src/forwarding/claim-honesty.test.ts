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
import { fabric } from "../core/data";
import type { Flow } from "../core/types";
import { describeGolden } from "../test-support/golden-sample";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "./ip";
import { isDefiniteDelivery, suggestedFlows, traceFlow, unobservedPolicyInputs } from "./engine";
import { GOLDEN_FORWARDING as G } from "../test-support/golden-expectations";
import { lazy } from "../test-support/test-subjects";

const CH = G.claimHonesty;

type Protocol = Flow["protocol"];

const flow = (srcIp: string, dstIp: string, protocol: Protocol, dstPort: number | null): Flow => ({ srcIp, dstIp, protocol, srcPort: null, dstPort });

describeGolden("an undecided delivery is not drawn as a resolved pass", () => {
  it("udp 10.0.30.10 → 10.0.10.7:53 (absence evidence) bands UNDETERMINED and names the gap", () => {
    const t = traceFlow(CH.absenceDelivery);
    expect(t.outcome).toBe("delivered");
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("INDETERMINATE");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.hops.map((h) => bandOfHopIn(h, t))).toEqual(["UNDETERMINED"]);
    expect(t.claim).toMatch(/not a decided pass/);
    expect(t.claim).toMatch(/binding not observed/);
  });

  it("tcp 10.0.20.50 → 10.0.10.50:443 at core2 (no ACLs collected) bands UNDETERMINED and names core2", () => {
    const t = traceFlow(CH.noAclDelivery);
    expect(t.outcome).toBe("delivered");
    expect(unobservedPolicyInputs(t).map((g) => [g.host, g.kind])).toContainEqual([G.sampleHosts.core2, "acl-uncollected"]);
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(bandOfHopIn(t.hops[t.hops.length - 1]!, t)).toBe("UNDETERMINED");
    expect(t.claim).toContain(`${G.sampleHosts.core2} holds a collected routing table but no collected ACLs`);
  });

  it("the flow once pinned as the definite delivery is router-originated, and is not RESOLVED", () => {
    /* REVERSED 2026-09-22 (auditor, B2). 10.0.30.1 is core1's own Vlan30 address; this test pinned it
       as the snapshot's definite delivery. A packet core1 originates arrives inbound on no interface,
       so it is refused, not walked. The RESOLVED-without-suffix branch is exercised on a host source in
       src/panels/decided-surfaces.counterfactual.test.tsx. */
    const t = traceFlow(CH.routerOriginated);
    expect(t.hops).toEqual([]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.claim).toContain(`an address of ${G.sampleHosts.core1} itself`);
  });

  it("a delivery resting on an FHRP ingress choice and an unobserved ingress port is not RESOLVED (critic B1)", () => {
    /* REVERSED 2026-09-21: tcp 10.0.10.50 -> 10.0.30.10:443 was pinned RESOLVED/SCOPED while its
       own caveat said core1 was ingress only by a point-in-time HSRP role ("traffic may enter via
       core2"). Traced from core2 it is dropped, and core2 holds no ACLs; and 8 core1 uplinks the
       source's frames could arrive by have no observed running configuration. */
    const t = traceFlow(G.headline.permit);
    const alt = G.headline.alternate;
    expect(t.outcome).toBe("delivered");
    const kinds = unobservedPolicyInputs(t).map((g) => [g.host, g.kind]);
    expect(kinds).toContainEqual([alt, "ingress-alternate"]);
    expect(kinds).toContainEqual([G.sampleHosts.core1, "ingress-port-unobserved"]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.claim).toContain(`may instead enter via ${alt} (${G.headline.alternateRole})`);
    /* UPDATED phase 3: traced from core2 the flow is no longer dropped (core2 now holds an OSPF default and
       routes 10.0.30.0/24 to core1), so the alternate is not modelled equivalently for the reasons its own
       trace records instead — core2's uncollected ACLs and its incomplete table. The class (every
       ingress-alternate gap is named in the claim it undecides) is the invariant block below. */
    expect(t.claim).toContain(`${alt} has no collected ACLs`);
    expect(t.claim).toContain(`the routing decision at ${alt} rests on a table the snapshot shows to be incomplete`);
  });

  it("over a sweep, the trace band is RESOLVED/REFUTED only for decided outcomes, and a delivered claim names its gap exactly when it is not definite", () => {
    const ips = CH.sweepAddresses;
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

/** Every suggested flow, and a grid between host addresses in every observed SVI subnet. */
function sweep(): Flow[] {
  const addrs = new Set<string>();
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    for (const off of [7, 10, 50]) {
      const h = a === null ? null : hostAddressIn(a.prefix, off);
      if (h !== null) addrs.add(formatIpv4(h));
    }
  }
  for (const e of fabric.endpoints) if (e.ip !== null) addrs.add(e.ip);
  const out: Flow[] = suggestedFlows().map((s) => s.flow);
  const services: [Protocol, number | null][] = [["tcp", 443], ["tcp", 22], ["udp", 53], ["icmp", null]];
  for (const s of addrs) for (const d of addrs) for (const [p, port] of services) out.push(flow(s, d, p, port));
  return out;
}

describe("an undecided outcome is never drawn as decided (invariant, over the loaded fabric)", () => {
  const tracesOf = lazy(() => sweep().map(traceFlow));

  it("the trace band is RESOLVED/REFUTED only for decided outcomes, and a delivered claim names its gap exactly when it is not definite", () => {
    const traces = tracesOf();
    let undecidedDeliveries = 0;
    let decided = 0;
    for (const t of traces) {
      const band = bandOfTrace(t);
      if (band !== "UNDETERMINED") {
        expect(isDecidedOutcome(t), JSON.stringify(t.flow)).toBe(true);
        decided += 1;
      }
      if (t.outcome !== "delivered") continue;
      const definite = isDefiniteDelivery(t);
      if (!definite) undecidedDeliveries += 1;
      expect(/not a decided pass/.test(t.claim), JSON.stringify(t.flow)).toBe(!definite);
      if (!definite) expect(t.hops.some((h) => bandOfHopIn(h, t) === "UNDETERMINED"), JSON.stringify(t.flow)).toBe(true);
    }
    expect(traces.length).toBeGreaterThan(0);
    expect(undecidedDeliveries + decided, "the sweep reaches banded outcomes").toBeGreaterThan(0);
  });

  it("every ingress-alternate gap that undecides a delivery or a refusal is named in that trace's own claim", () => {
    /* The class behind critic B1's "traced from core2 this flow is dropped": the alternate's reason is
       stated in the one sentence a reader quotes, whatever the reason is on this data. */
    let named = 0;
    for (const t of tracesOf()) {
      if (t.outcome !== "delivered" && t.outcome !== "denied" && t.outcome !== "dropped") continue;
      if (t.outcome === "delivered" && isDefiniteDelivery(t)) continue;
      for (const g of unobservedPolicyInputs(t).filter((x) => x.kind === "ingress-alternate")) {
        expect(t.claim, JSON.stringify(t.flow)).toContain(g.label);
        named += 1;
      }
    }
    const fhrpPair = fabric.l3.some((r) => r.fhrpRole !== null && r.fhrpRole.toLowerCase() === "standby");
    if (fhrpPair) expect(named, "ingress-alternate gaps named in claims (an FHRP pair exists)").toBeGreaterThan(0);
  });
});

describeGolden("a flow inside one subnet is not modelled as routed", () => {
  it("tcp 10.0.30.10 → 10.0.30.20 is not a decided denial by PROTECT_SERVERS", () => {
    const t = traceFlow(CH.sameSubnet.flow);
    expect(t.outcome).toBe("indeterminate");
    expect(t.hops).toEqual([]);
    expect(isDecidedOutcome(t)).toBe(false);
    expect(t.claim).toContain(`both lie in ${CH.sameSubnet.subnet}`);
    expect(t.claim).toMatch(/bridged at L2/);
    expect(t.claim).not.toContain(CH.sameSubnet.list);
  });

  it("udp and icmp 10.0.10.50 → 10.0.10.7 are not denied by INET_RETURN", () => {
    const V = CH.sameSubnetVlan10;
    for (const [p, port] of [["udp", 53], ["icmp", null]] as [Protocol, number | null][]) {
      const t = traceFlow(flow(V.src, V.dst, p, port));
      expect(t.outcome, p).toBe("indeterminate");
      expect(t.claim, p).not.toContain(V.list);
    }
  });

  it("a flow that does cross subnets is still routed", () => {
    expect(traceFlow(CH.crossSubnet).hops.length).toBeGreaterThan(0);
  });
});
