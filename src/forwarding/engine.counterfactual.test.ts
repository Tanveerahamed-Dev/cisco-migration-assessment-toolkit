/**
 * engine.counterfactual.test.ts — the DECIDED branches of the engine, exercised on the real
 * compiled snapshot with two completeness producers answered counterfactually.
 *
 * Why this file exists (2026-09-22 auditor, B1 + B2). On the shipped snapshot NO trace is decided:
 *  - every decided verdict the fabric used to produce was sourced from a router's OWN address, which
 *    the engine now refuses as router-originated (inbound interface ACLs do not filter it); and
 *  - every remaining delivery or denial is reached through a route chosen from core1's or core2's
 *    table, which the snapshot shows to be incomplete, so none of them is decided either.
 * That is the honest answer, and engine.test.ts pins it. But it leaves the decided branches — the
 * definite delivery, the counterexample search and its citations, the SCOPED ceiling — with no real
 * trace to run on, and a guard whose success path is never executed is not a guard.
 *
 * So this file asks the engine the counterfactual question "what if core1's and core2's collected
 * routing tables were complete" (and, where a test says so, "what if every physical port a source
 * could arrive by were observed binding no list"). Only those two COMPLETENESS producers are
 * replaced; every route, ACL line, binding, SVI and FHRP record is the real compiled evidence, and
 * every assertion runs through the real `traceFlow`. Vitest isolates modules per file, so the
 * counterfactual cannot leak into any other test or into the product.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const cf = vi.hoisted(() => ({ portsObserved: false }));

vi.mock("./rib-completeness", async (orig) => {
  const actual = await orig<typeof import("./rib-completeness")>();
  return { ...actual, ribIncompleteness: () => [], ribIncompletenessSentence: () => null };
});
vi.mock("./bindings", async (orig) => {
  const actual = await orig<typeof import("./bindings")>();
  return {
    ...actual,
    physicalIngressStates: (...args: Parameters<typeof actual.physicalIngressStates>) =>
      cf.portsObserved ? [] : actual.physicalIngressStates(...args),
  };
});

import { bandOfTrace, claimBadge } from "../core/claims";
import { aclsOf } from "../core/data";
import type { Flow } from "../core/types";
import { counterexample, isDefiniteDelivery, isDefiniteOnModelledPath, traceFlow, unobservedPolicyInputs } from "./engine";

const udp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "udp", dstPort, srcPort: null });
const tcp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });

beforeEach(() => {
  cf.portsObserved = false;
});

describe("counterfactual: complete routing tables — the decided delivery", () => {
  it("the headline flow, whose bindings WERE observed, is decided by the bound list alone", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443));
    expect(t.outcome).toBe("delivered");
    const hop = t.hops[0]!;
    const cites = hop.evidence.map((e) => e.cite);
    expect(cites).toContain("acls.core1.PROTECT_SERVERS[0]");
    expect(cites).not.toContain("acls.core1.INET_RETURN[0]");
    expect(hop.evidence.find((e) => e.cite === "interfaces.core1.Vlan30")?.raw).toBe("acl_out: PROTECT_SERVERS");
    // Decided on the modelled path; the ingress before it is still assumed, so not definite, not SCOPED.
    expect(isDefiniteOnModelledPath(t)).toBe(true);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
  });

  it("a delivery at a host whose ACLs WERE collected and decide nothing against it stays definite on its path", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.20.10", 22));
    expect(t.outcome).toBe("delivered");
    expect(isDefiniteOnModelledPath(t)).toBe(true);
    expect(t.caveats.join(" ")).toMatch(/none is bound to the interfaces this flow enters \(Vlan10\) or leaves \(Vlan20\)/);
    expect(unobservedPolicyInputs(t).map((g) => g.kind).sort()).toEqual(["ingress-alternate", "ingress-port-unobserved"]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
  });

  it("SCOPED is reachable where nothing before or on the modelled path is assumed", () => {
    /* 10.0.30.0/24 has one gateway (core1 Vlan30), so there is no FHRP alternate; with its physical
       ingress ports counterfactually observed, nothing is assumed and the badge reaches its ceiling. */
    cf.portsObserved = true;
    const t = traceFlow(tcp("10.0.30.5", "10.0.10.50", 443));
    expect(t.outcome).toBe("delivered");
    expect(unobservedPolicyInputs(t)).toEqual([]);
    expect(isDefiniteDelivery(t)).toBe(true);
    expect(claimBadge(t)).toBe("SCOPED");
    expect(bandOfTrace(t)).toBe("RESOLVED");
  });

  it("no trace anywhere is 'delivered' while carrying the never-a-definite-permit caveat", () => {
    cf.portsObserved = true;
    const srcs = ["10.0.10.50", "10.0.10.77", "10.0.10.5", "10.0.20.50", "10.0.30.5", "10.0.40.50"];
    const dsts = ["10.0.10.10", "10.0.20.10", "10.0.30.10", "10.0.40.10"];
    const flows = srcs.flatMap((s) => dsts.flatMap((d) => [...[22, 443, 3389, 8080].map((p) => tcp(s, d, p)), udp(s, d, 53)]));
    let caveated = 0;
    let definite = 0;
    let heldBackByAbsence = 0;
    for (const f of flows) {
      const t = traceFlow(f);
      const label = JSON.stringify(f);
      if (t.caveats.some((c) => /never a definite permit/.test(c))) {
        caveated += 1;
        expect(t.outcome, label).not.toBe("delivered");
      }
      if (t.outcome === "delivered" && unobservedPolicyInputs(t).length === 0) {
        const undecidedOnPath = t.hops.some((h) => h.verdict === "unmodeled" || h.evidence.some((e) => e.kind === "absence"));
        expect(isDefiniteDelivery(t), label).toBe(!undecidedOnPath);
        if (undecidedOnPath) heldBackByAbsence += 1;
        else definite += 1;
      }
    }
    expect(caveated).toBeGreaterThan(0);
    expect(definite).toBeGreaterThan(0);
    expect(heldBackByAbsence).toBeGreaterThan(0);
  });
});

describe("counterfactual: complete routing tables — the counterexample search", () => {
  const aclCites = (text: string): string[] => text.match(/acls\.[A-Za-z0-9_.-]+\[\d+\]/g) ?? [];
  const consultedCites = (flow: Flow): Set<string> => {
    const cites = new Set<string>();
    for (const hop of traceFlow(flow).hops) {
      if (hop.decidedBy !== null) cites.add(hop.decidedBy.cite);
      for (const e of hop.evidence) cites.add(e.cite);
    }
    return cites;
  };

  it("offers no counterexample whose own delivery is undecided", () => {
    const flow = tcp("10.0.10.50", "10.0.30.10", 3389);
    const trace = traceFlow(flow);
    expect(trace.outcome).toBe("denied");
    const cx = counterexample(flow, trace);
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(isDefiniteOnModelledPath(cx.trace)).toBe(true);
    expect(cx.trace.hops.flatMap((h) => h.evidence).some((e) => e.kind === "absence")).toBe(false);
    expect(cx.rationale).toMatch(/same ingress assumption as the flow above/);
  });

  it("any counterexample it does offer is a definite delivery", () => {
    const dropFlow = udp("10.0.10.50", "10.0.40.5", 53);
    const dropped = traceFlow(dropFlow);
    expect(dropped.outcome).toBe("denied");
    const cx = counterexample(dropFlow, dropped);
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(isDefiniteOnModelledPath(cx.trace)).toBe(true);
    expect(cx.trace.caveats.some((c) => /never a definite permit/.test(c))).toBe(false);
  });

  it("cites the line its own trace was decided by, not the line that generated the candidate", () => {
    /* HOLLOW until 2026-09-22 (acceptance report, F2): this used to loop `toContain` over the cited
       lines — and the rationale cites none, so the loop ran zero times and only `cited == []`
       asserted anything. It now proves both halves of its name, with preconditions that make each
       half reachable: the candidate's OWN trace consulted no ACL line (so "no line" is the correct
       citation), and the blocking host DOES hold the permit lines that generate candidates (so a
       rationale narrated from the generator would have had a line to mis-cite). */
    const dropFlow = udp("10.0.10.50", "10.0.40.5", 53);
    const dropped = traceFlow(dropFlow);
    const cx = counterexample(dropFlow, dropped);
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    const fresh = traceFlow(cx.flow);
    expect(fresh.outcome).toBe("delivered");
    const decidedByOwnTrace = [...consultedCites(cx.flow)].filter((c) => /^acls\./.test(c));
    expect(decidedByOwnTrace, "precondition: the candidate's own trace consulted no ACL line").toEqual([]);
    const blockingHost = dropped.hops[dropped.hops.length - 1]!.host;
    const generators = Object.entries(aclsOf(blockingHost)).flatMap(([, lines]) =>
      lines.filter((l) => (l.action ?? "").toLowerCase() === "permit").map((l) => l.cite),
    );
    expect(generators.length, "precondition: the blocking host holds permit lines that generate candidates").toBeGreaterThan(0);
    const cited = aclCites(cx.rationale);
    // Half one: the rationale cites exactly what its own trace was decided by — here, no line.
    expect(cited).toEqual(decidedByOwnTrace);
    expect(cx.rationale).toMatch(/No ACL line was consulted/);
    // Half two: no line that GENERATED a candidate is cited in its place.
    for (const g of generators) expect(cx.rationale).not.toContain(g);
  });

  it("cites a line its own trace consulted — on the flow that originally mis-cited MGMT_IN[0]", () => {
    const denied = tcp("10.0.10.50", "10.0.30.10", 53);
    const cx = counterexample(denied, traceFlow(denied));
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(traceFlow(cx.flow).outcome).toBe("delivered");
    const cited = aclCites(cx.rationale);
    expect(cited.length).toBeGreaterThan(0);
    const consulted = consultedCites(cx.flow);
    for (const cite of cited) expect([...consulted]).toContain(cite);
    expect(cited).not.toContain("acls.core1.MGMT_IN[0]");
  });

  it("every counterexample rationale that cites an ACL line cites one its own fresh trace consulted (sweep)", () => {
    const addrs = ["10.0.10.50", "10.0.20.10", "10.0.30.10", "10.0.30.50", "10.0.40.5", "10.0.99.10", "203.0.113.9"];
    let citing = 0;
    let checked = 0;
    const violations: string[] = [];
    for (const protocol of ["tcp", "udp"] as const)
      for (const dstPort of [22, 53, 80, 443, 161, 3389])
        for (const srcIp of addrs)
          for (const dstIp of addrs) {
            if (srcIp === dstIp) continue;
            const flow: Flow = { srcIp, dstIp, protocol, dstPort, srcPort: null };
            const cx = counterexample(flow, traceFlow(flow));
            if (!cx.found) continue;
            const cited = aclCites(cx.rationale);
            if (cited.length === 0) continue;
            citing += 1;
            const consulted = consultedCites(cx.flow);
            for (const cite of cited) {
              checked += 1;
              if (!consulted.has(cite)) violations.push(`${protocol}/${dstPort} ${srcIp}->${dstIp}: ${cite}`);
            }
          }
    expect(citing).toBeGreaterThan(0);
    expect(checked).toBeGreaterThan(0);
    expect(violations).toEqual([]);
  });
});
