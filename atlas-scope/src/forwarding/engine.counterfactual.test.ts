/**
 * engine.counterfactual.test.ts — the DECIDED branches of the engine, exercised on the real
 * compiled snapshot with two completeness producers answered counterfactually.
 *
 * UPDATED phase 3: the regenerated sample DOES produce decided traces (a two-hop delivery and a two-hop
 * denial through dist1 -> core1; see engine.suggestions.test.ts), so the decided branches now also run on
 * the real completeness producers. This file keeps the counterfactual for the cases the real data still
 * leaves undecided (core2's table, the unobserved core1 ports); its sample-specific blocks are golden
 * (../test-support/golden-sample.ts) and the two that pinned old-sample flows are re-expressed by property.
 *
 * Why this file exists (2026-09-22 auditor, B1 + B2). On the then-shipped snapshot NO trace was decided:
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
import { aclsOf, fabric } from "../core/data";
import { describeGolden } from "../test-support/golden-sample";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "./ip";
import type { Flow } from "../core/types";
import { counterexample, isDefiniteDelivery, isDefiniteOnModelledPath, traceFlow, unobservedPolicyInputs } from "./engine";
import { GOLDEN_FORWARDING as G } from "../test-support/golden-expectations";
import { lazy, need, needSome } from "../test-support/test-subjects";

const C1 = G.core1Acls;
const PS = C1.protectServers;

const udp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "udp", dstPort, srcPort: null });
const tcp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });

beforeEach(() => {
  cf.portsObserved = false;
});

/** Every ACL-line citation in a sentence (one helper for the file: the invariant block's copy had lost its
 *  escapes — `/acls.[A-Za-z0-9_.-]+[d+]/` — and matched almost nothing, so "cites exactly its own trace's
 *  lines" compared [] with [] whatever the rationale said). */
const aclCites = (text: string): string[] => text.match(/acls\.[A-Za-z0-9_.-]+\[\d+\]/g) ?? [];
/** Every cite a flow's own fresh trace consulted: each hop's decider and every piece of its evidence. */
const consultedCites = (flow: Flow): Set<string> => {
  const cites = new Set<string>();
  for (const hop of traceFlow(flow).hops) {
    if (hop.decidedBy !== null) cites.add(hop.decidedBy.cite);
    for (const e of hop.evidence) cites.add(e.cite);
  }
  return cites;
};

describeGolden("counterfactual: complete routing tables — the decided delivery", () => {
  it("the headline flow, whose bindings WERE observed, is decided by the bound list alone", () => {
    const t = traceFlow(G.headline.permit);
    expect(t.outcome).toBe("delivered");
    const hop = t.hops[0]!;
    const cites = hop.evidence.map((e) => e.cite);
    expect(cites).toContain(PS.permit443Cite);
    expect(cites).not.toContain(C1.inetReturn.establishedCite);
    expect(hop.evidence.find((e) => e.cite === PS.bindingCite)?.raw).toBe(PS.bindingRaw);
    // Decided on the modelled path; the ingress before it is still assumed, so not definite, not SCOPED.
    expect(isDefiniteOnModelledPath(t)).toBe(true);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
  });

  it("a delivery at a host whose ACLs WERE collected and decide nothing against it stays definite on its path", () => {
    const L = G.flows.localDelivery;
    const t = traceFlow(L.flow);
    expect(t.outcome).toBe("delivered");
    expect(isDefiniteOnModelledPath(t)).toBe(true);
    expect(t.caveats.join(" ")).toContain(`none is bound to the interfaces this flow enters (${L.enters}) or leaves (${L.leaves})`);
    expect(unobservedPolicyInputs(t).map((g) => g.kind).sort()).toEqual([...G.headline.gapKinds]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
  });

  it("SCOPED is reachable where nothing before or on the modelled path is assumed", () => {
    /* 10.0.30.0/24 has one gateway (core1 Vlan30), so there is no FHRP alternate; with its physical
       ingress ports counterfactually observed, nothing is assumed and the badge reaches its ceiling. */
    cf.portsObserved = true;
    const t = traceFlow(G.counterfactual.scoped);
    expect(t.outcome).toBe("delivered");
    expect(unobservedPolicyInputs(t)).toEqual([]);
    expect(isDefiniteDelivery(t)).toBe(true);
    expect(claimBadge(t)).toBe("SCOPED");
    expect(bandOfTrace(t)).toBe("RESOLVED");
  });

  it("no trace anywhere is 'delivered' while carrying the never-a-definite-permit caveat", () => {
    cf.portsObserved = true;
    const { srcs, dsts } = G.counterfactual.neverADefinitePermitSweep;
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

/** A grid between host addresses in every observed SVI subnet, over tcp and udp — refusals to search around. */
function refusalSweep(): Flow[] {
  const addrs = new Set<string>();
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    for (const off of [5, 10]) {
      const h = a === null ? null : hostAddressIn(a.prefix, off);
      if (h !== null) addrs.add(formatIpv4(h));
    }
  }
  for (const e of fabric.endpoints) if (e.ip !== null) addrs.add(e.ip);
  const out: Flow[] = [];
  for (const s of [...addrs].sort())
    for (const d of [...addrs].sort())
      if (s !== d) for (const [p, port] of [["tcp", 22], ["tcp", 3389], ["udp", 53]] as const) out.push({ srcIp: s, dstIp: d, protocol: p, dstPort: port, srcPort: null });
  return out;
}

describe("counterfactual: complete routing tables — the counterexample search (invariant)", () => {
  /** Every refusal in the sweep whose counterexample search found one — computed once, on first use. */
  const found = lazy((): { flow: Flow; refused: ReturnType<typeof traceFlow>; cx: Extract<ReturnType<typeof counterexample>, { found: true }> }[] =>
    refusalSweep().flatMap((flow) => {
      const refused = traceFlow(flow);
      if (refused.outcome !== "denied" && refused.outcome !== "dropped") return [];
      const cx = counterexample(flow, refused);
      return cx.found ? [{ flow, refused, cx }] : [];
    }),
  );

  it("any counterexample it does offer is a definite delivery (over every refusal in the sweep)", (ctx) => {
    /* UPDATED phase 3: this pinned udp 10.0.10.50 -> 10.0.40.5:53 as a denial; on the regenerated sample
       10.0.40.0/24 is routed to dist1 and that flow is delivered, so the subject is now every refusal the
       sweep finds a counterexample for — the class, not the instance. */
    const all = found();
    for (const { flow, cx } of all) {
      expect(isDefiniteOnModelledPath(cx.trace), JSON.stringify(flow)).toBe(true);
      expect(cx.trace.caveats.some((c) => /never a definite permit/.test(c)), JSON.stringify(flow)).toBe(false);
    }
    needSome(ctx, all.length, "refusal in the sweep whose counterexample search finds one");
  });

  it("cites the line its own trace was decided by, not the line that generated the candidate", (ctx) => {
    /* HOLLOW until 2026-09-22 (acceptance report, F2): this used to loop `toContain` over the cited
       lines — and the rationale cites none, so the loop ran zero times and only `cited == []`
       asserted anything. It now proves both halves of its name, with preconditions that make each
       half reachable: the candidate's OWN trace consulted no ACL line (so "no line" is the correct
       citation), and the blocking host DOES hold the permit lines that generate candidates (so a
       rationale narrated from the generator would have had a line to mis-cite).
       UPDATED phase 3: the subject (once udp 10.0.10.50 -> 10.0.40.5:53) is resolved by those two
       preconditions over the sweep, since the regenerated sample delivers that flow. */
    const subject = found().find(({ refused, cx }) => {
      const own = [...consultedCites(cx.flow)].filter((c) => /^acls\./.test(c));
      const blockingHost = refused.hops[refused.hops.length - 1]!.host;
      const generators = Object.values(aclsOf(blockingHost)).flatMap((lines) => lines.filter((l) => (l.action ?? "").toLowerCase() === "permit"));
      return own.length === 0 && generators.length > 0;
    });
    const { refused, cx } = need(ctx, subject, "found counterexample whose own trace consulted no ACL line, at a host holding permit lines");
    const fresh = traceFlow(cx.flow);
    expect(fresh.outcome).toBe("delivered");
    const decidedByOwnTrace = [...consultedCites(cx.flow)].filter((c) => /^acls\./.test(c));
    expect(decidedByOwnTrace, "precondition: the candidate's own trace consulted no ACL line").toEqual([]);
    const blockingHost = refused.hops[refused.hops.length - 1]!.host;
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
});

describeGolden("counterfactual: complete routing tables — the counterexample search", () => {

  it("offers no counterexample whose own delivery is undecided", () => {
    const flow = G.headline.deny;
    const trace = traceFlow(flow);
    expect(trace.outcome).toBe("denied");
    const cx = counterexample(flow, trace);
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(isDefiniteOnModelledPath(cx.trace)).toBe(true);
    expect(cx.trace.hops.flatMap((h) => h.evidence).some((e) => e.kind === "absence")).toBe(false);
    expect(cx.rationale).toMatch(/same ingress assumption as the flow above/);
  });

  /* MOVED phase 3: "any counterexample it does offer is a definite delivery" and "cites the line its own
     trace was decided by, not the line that generated the candidate" pinned udp 10.0.10.50 -> 10.0.40.5:53
     as a denial; the regenerated sample routes 10.0.40.0/24 to dist1 and delivers it. Both are re-expressed
     above by property ("... (invariant)" block), over every refusal the sweep finds a counterexample for. */

  it("cites a line its own trace consulted — on the flow that originally mis-cited MGMT_IN[0]", () => {
    const denied = G.headline.tcp53;
    const cx = counterexample(denied, traceFlow(denied));
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(traceFlow(cx.flow).outcome).toBe("delivered");
    const cited = aclCites(cx.rationale);
    expect(cited.length).toBeGreaterThan(0);
    const consulted = consultedCites(cx.flow);
    for (const cite of cited) expect([...consulted]).toContain(cite);
    expect(cited).not.toContain(C1.mgmtIn.lineCite);
  });

  it("every counterexample rationale that cites an ACL line cites one its own fresh trace consulted (sweep)", () => {
    const addrs = G.counterfactual.citationSweepAddresses;
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
