/**
 * engine.test.ts — the forwarding simulator, driven entirely by the real compiled snapshot.
 *
 * Every expectation below is derived from `src/data/fabric.json` as it actually is (core1 + core2
 * are the only hosts with a collected RIB; core1 is the only host with collected ACLs). No fixture
 * is fabricated: a hand-made RIB shaped the way the matcher expects would simply agree with a
 * matcher bug. Where a construct this fabric happens not to contain has to be exercised, the record
 * comes verbatim from the engine's OWN parser — see PRODUCER below.
 */
import { describe, expect, it } from "vitest";
import { fabric, hasRib, linksByHost, routesOf } from "../core/data";
import { bandOfHop, bandOfTrace, claimBadge, scopeTuple, T1_verdict } from "../core/claims";
import type { AclLine, Flow } from "../core/types";
import { addressRoleIn, formatIpv4, parseInterfaceAddress, parseIpv4, parsePrefix, prefixContains } from "./ip";
import {
  ACL_PASSES_PER_HOP,
  blockingHop,
  chooseRoute,
  COUNTEREXAMPLE_CANDIDATE_CAP,
  counterexample,
  engineWork,
  evaluateAcls,
  ingressCandidates,
  isDefiniteDelivery,
  isDefiniteOnModelledPath,
  lineEvaluability,
  matchTri,
  resolveEgress,
  resolveNextHost,
  resolveObjectGroup,
  refusalOf,
  suggestedFlows,
  TTL_LIMIT,
  traceFlow,
  unobservedPolicyInputs,
} from "./engine";

const udp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "udp", dstPort, srcPort: null });

const tcp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({
  srcIp,
  dstIp,
  protocol: "tcp",
  dstPort,
  srcPort: null,
});

/* ── ACL lines from the REAL producer, not from this test's imagination ──────
   `fabric.json` contains no ACE with an unresolved service name or a port list, so the constructs
   below cannot be taken from it. They are instead the verbatim stdout of the engine's own parser,
   which is the producer this model compiles:

     cd <the engine repository root — the parent of atlas-scope/>
     py -3.12 -c "import json; from cisco_toolkit.parse import _acl_rule; \
                  print(json.dumps(_acl_rule('permit','tcp ... eq citrix', True), sort_keys=True))"

   Hand-shaping these would be the fixture trap — a record built the way the matcher expects simply
   agrees with the matcher's bug.

   UPDATED 2026-09-21: `tools/compile-snapshot.mjs` originally dropped the producer's own warnings
   (`unevaluable`, `unmodeled_qualifiers`) and now carries them. `compiled()` below still strips
   them, and that is now DELIBERATE rather than incidental: it feeds the engine the worst case, so
   these tests prove the structural guard stands on its own and does not quietly depend on the
   producer having flagged the line. A guard that only works when it is also told the answer is
   not a guard. `producer-trust.test.ts` covers the other direction — that the flags, when
   present, are honoured. */
const PRODUCER = {
  citrix: {
    action: "permit",
    dport: { op: "eq", val: null },
    dst: { ip: "10.0.30.0", wild: "0.0.0.255" },
    proto: "tcp",
    raw: "permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq citrix",
    sport: null,
    src: { ip: "10.0.10.0", wild: "0.0.0.255" },
    unevaluable: true,
  },
  rangeDynamic: {
    action: "permit",
    dport: { op: "range", val: 16384, val2: null },
    dst: { ip: "10.0.30.0", wild: "0.0.0.255" },
    proto: "udp",
    raw: "permit udp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 range 16384 dynamic",
    sport: null,
    src: { ip: "10.0.10.0", wild: "0.0.0.255" },
    unevaluable: true,
  },
  portList: {
    action: "permit",
    dport: { op: "eq", val: 443 },
    dst: { ip: "10.0.30.0", wild: "0.0.0.255" },
    proto: "tcp",
    raw: "permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443 8443",
    sport: null,
    src: { ip: "10.0.10.0", wild: "0.0.0.255" },
    unmodeled_qualifiers: ["unrecognized_trailing_match_tokens"],
  },
  denyAll: {
    action: "deny",
    dport: null,
    dst: { ip: "0.0.0.0", wild: "255.255.255.255" },
    proto: "ip",
    raw: "deny ip any any",
    sport: null,
    src: { ip: "0.0.0.0", wild: "255.255.255.255" },
  },
} as const;

/** The exact field mapping tools/compile-snapshot.mjs applies — including what it drops. */
function compiled(rule: (typeof PRODUCER)[keyof typeof PRODUCER], acl: string, index: number): AclLine {
  const r = rule as unknown as Record<string, unknown>;
  const field = (k: string): AclLine["src"] => {
    const v = r[k] as { ip?: string; wild?: string; group?: string } | null;
    return v ? { ip: v.ip ?? null, wild: v.wild ?? null, group: v.group ?? null } : null;
  };
  return {
    index,
    action: (r["action"] as string | undefined) ?? null,
    raw: (r["raw"] as string | undefined) ?? null,
    proto: (r["proto"] as string | undefined) ?? null,
    src: field("src"),
    dst: field("dst"),
    sport: (r["sport"] as AclLine["sport"]) ?? null,
    dport: (r["dport"] as AclLine["dport"]) ?? null,
    /* The producer's own warnings are STRIPPED here on purpose — see the note above PRODUCER.
       Spelled out rather than omitted so the deliberate loss is visible at the call site: these
       tests must prove the structural guard works with no help from the flags. */
    unevaluable: false,
    unmodeledQualifiers: [],
    established: false,
    icmpType: null,
    timeRange: null,
    cite: `acls.core1.${acl}[${index}]`,
  };
}

describe("the data this suite is written against", () => {
  it("still holds RIBs for exactly core1 and core2, and ACLs for core1 only", () => {
    expect(fabric.coverage.routableHosts).toEqual(["core1", "core2"]);
    expect(fabric.coverage.aclHosts).toEqual(["core1"]);
    expect(fabric.devices.length).toBe(26);
    expect(hasRib("dist1")).toBe(false);
  });
});

describe("a permit that steps over an undecidable line is not a delivery", () => {
  /* REWRITTEN 2026-09-21 (A3). This block used to pin tcp 10.0.10.50 -> 10.0.30.10:443 as
     INDETERMINATE, decided by INET_RETURN[0] — a list the specificity rule did not apply "with no
     binding collected". That premise was false: the snapshot binds PROTECT_SERVERS outbound on
     core1 Vlan30 and nothing on Vlan10, and INET_RETURN is bound on neither, so INET_RETURN[0]
     cannot touch that flow. The headline flow is now pinned below as the observed-binding case.

     The PROPERTY this block exists for still holds wherever a binding is unknown, and is pinned on
     a flow where one really is: 10.0.30.50 -> 10.0.10.77:443 leaves core1 by Vlan10, whose access
     port Gi1/0/5 carries an outbound access-group the collector did not name
     (candidate_projection_incomplete), and 10.0.10.77's attachment port was never observed. */
  const trace = traceFlow(tcp("10.0.30.50", "10.0.10.77", 443));

  it("reaches core1's connected route, but the verdict follows the caveat: indeterminate", () => {
    expect(trace.outcome).toBe("indeterminate");
    const last = trace.hops[trace.hops.length - 1]!;
    expect(last.host).toBe("core1");
    expect(last.verdict).toBe("unmodeled");
    expect(bandOfHop(last)).toBe("UNDETERMINED");
    expect(last.decidedBy?.cite).toBe("acls.core1.INET_RETURN[0]");
    expect(last.outIntf).toBe("Vlan10");
    // The unknown binding that forced the fallback is itself cited, as an absence.
    expect(last.evidence.some((e) => e.kind === "absence" && e.cite === "interfaces.core1.Gi1/0/5")).toBe(true);
    expect(trace.caveats.join(" ")).toMatch(/Gi1\/0\/5 out \(the collector recorded an outbound access-group candidate/);
    // The forwarding fact survives as a separate, cited statement.
    expect(last.evidence.some((e) => e.kind === "route" && e.cite === "routes.core1[2]")).toBe(true);
    expect(trace.claim).toContain("connected 10.0.10.0/24 (routes.core1[2])");
    expect(trace.claim).not.toMatch(/is delivered/);
    expect(isDefiniteDelivery(trace)).toBe(false);
  });

  it("the headline flow, whose bindings WERE observed, is decided by the bound list alone", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443));
    expect(t.outcome).toBe("delivered");
    const hop = t.hops[0]!;
    expect(hop.verdict).toBe("delivered");
    const cites = hop.evidence.map((e) => e.cite);
    expect(cites).toContain("acls.core1.PROTECT_SERVERS[0]");
    expect(cites).not.toContain("acls.core1.INET_RETURN[0]");
    // The binding that applies PROTECT_SERVERS here is evidence, cited to its interface record.
    const binding = hop.evidence.find((e) => e.cite === "interfaces.core1.Vlan30");
    expect(binding?.raw).toBe("acl_out: PROTECT_SERVERS");
    /* Decided by the bound list ON THE MODELLED PATH — but not definite, and not SCOPED: core1 is the
       ingress only by a point-in-time HSRP role (traced from core2 it drops), and the core1 uplinks
       the source could arrive by were never observed (critic B1, 2026-09-21). */
    /* UPDATED 2026-09-22 (auditor, B1): the delivery rests on core1's connected 10.0.30.0/24, chosen
       from a table the snapshot shows to be incomplete, so even the modelled path is not decided here.
       The decided branch is exercised in engine.counterfactual.test.ts with complete tables. */
    expect(isDefiniteOnModelledPath(t)).toBe(false);
    expect(unobservedPolicyInputs(t).map((g) => g.kind)).toContain("rib-partial");
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
  });

  it("no trace anywhere is 'delivered' while carrying the never-a-definite-permit caveat", () => {
    /* Both guards below used to be conditional on a sweep that never reached them (36 flows from
       sources whose bindings are all observed): the test ran green with zero assertions (critic F2,
       2026-09-22). The sweep now includes the sources that DO reach each branch — 10.0.10.77 and
       10.0.10.1 (specificity-mode ACL choice on core1, which yields the caveat) and 10.0.30.1 (core1's
       own SVI, no ingress gap) — and every branch is counted and required to have run. */
    const srcs = ["10.0.10.50", "10.0.10.77", "10.0.10.1", "10.0.20.50", "10.0.30.1", "10.0.40.50"];
    const dsts = ["10.0.10.10", "10.0.20.10", "10.0.30.10", "10.0.30.1"];
    const flows = srcs.flatMap((s) =>
      dsts.flatMap((d) => [...[22, 443, 3389, 8080].map((p) => tcp(s, d, p)), udp(s, d, 53)]),
    );
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
      /* A delivery with no unobserved policy input is definite exactly when no hop on its path is
         unmodelled and no evidence item records an absence (an unnamed access-group, an unobserved
         attachment port). The old guard omitted the second half and would have been false had it
         ever run: udp 10.0.30.1 -> 10.0.10.10:53 has no gap yet is held back by Gi1/0/5's absence. */
      if (t.outcome === "delivered" && unobservedPolicyInputs(t).length === 0) {
        const undecidedOnPath = t.hops.some((h) => h.verdict === "unmodeled" || h.evidence.some((e) => e.kind === "absence"));
        expect(isDefiniteDelivery(t), label).toBe(!undecidedOnPath);
        if (undecidedOnPath) heldBackByAbsence += 1;
        else definite += 1;
      }
    }
    expect(caveated).toBeGreaterThan(0);
    /* UPDATED 2026-09-22 (auditor, B1 + B2): the definite deliveries this sweep used to reach were
       all sourced by core1's own SVI (now refused as router-originated) or rested on core1's
       incomplete table. On this snapshot none is definite and none is held back only by an absence;
       both branches run in engine.counterfactual.test.ts. */
    expect(definite).toBe(0);
    expect(heldBackByAbsence).toBe(0);
  });

  it("shows the routes it beat, so 'why not that one' is answerable", () => {
    const last = trace.hops[trace.hops.length - 1]!;
    expect(last.alternatives.map((a) => a.prefix)).toEqual(["10.0.0.0/16", "0.0.0.0/0"]);
  });

  it("records the permitting ACL line as evidence even though it did not block", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443));
    const acl = t.hops[0]!.evidence.find((e) => e.cite === "acls.core1.PROTECT_SERVERS[0]");
    expect(acl?.raw).toBe("permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443");
  });

  it("still qualifies the claim over what was collected", () => {
    expect(trace.caveats.length).toBeGreaterThan(0);
    expect(trace.caveats.join(" ")).toMatch(/access-group|binding/i);
    expect(trace.claim).toMatch(/cannot be decided/);
    expect(trace.claim).toMatch(/core1/);
  });
});

describe("delivered", () => {
  /* REVERSED 2026-09-21. This block used to read "core2 holds a RIB and no collected ACL, so a flow
     it delivers carries no undecided input" — encoding the defect as intent. A host with no
     collected ACL is a filtering question nobody asked, not one answered "permit": the trace's own
     caveat says "filtering there is unobserved, not absent". So the core2 delivery is a real
     routing fact, but it is NOT definite, it cannot earn SCOPED, and it is never a counterexample. */
  const trace = traceFlow(tcp("10.0.20.10", "10.0.10.10", 443));

  it("is delivered on core2's connected route, but core2's missing ACLs keep it from being definite", () => {
    expect(trace.outcome).toBe("delivered");
    const last = trace.hops[trace.hops.length - 1]!;
    expect(last.host).toBe("core2");
    expect(last.verdict).toBe("delivered");
    expect(last.decidedBy?.kind).toBe("route");
    expect(trace.claim).toMatch(/is delivered/);
    const gaps = unobservedPolicyInputs(trace);
    expect(gaps.map((g) => [g.host, g.kind])).toContainEqual(["core2", "acl-uncollected"]);
    // Ingress-side gaps may add to it; none may be an ACL gap on a host OFF this path.
    expect(gaps.filter((g) => g.kind === "acl-uncollected").map((g) => g.host)).toEqual(["core2"]);
    expect(isDefiniteDelivery(trace)).toBe(false);
    expect(claimBadge(trace)).toBe("PARTIAL");
    expect(T1_verdict(trace)).toMatch(/no ACLs collected for core2/);
  });

  it("records the ACL gap at a hop that STOPS the trace too — unmodeled (dist1) and no-route (core2)", () => {
    /* The gap was once recorded only for passing verdicts, so these two traces printed "no
       filtering question on this path was left unobserved" beside their own caveat "No ACLs were
       collected for <host>". Critic B1, 2026-09-21. */
    const unmodeled = traceFlow(tcp("10.0.40.50", "10.0.30.10", 443));
    expect(unmodeled.hops.some((h) => h.host === "dist1" && h.verdict === "unmodeled")).toBe(true);
    expect(unobservedPolicyInputs(unmodeled).map((g) => [g.host, g.kind])).toContainEqual(["dist1", "acl-uncollected"]);
    expect(T1_verdict(unmodeled)).toMatch(/no ACLs collected for dist1/);

    const noRoute = traceFlow(tcp("10.0.20.50", "198.51.100.7", 443));
    expect(noRoute.hops.some((h) => h.host === "core2" && h.verdict === "no-route")).toBe(true);
    expect(unobservedPolicyInputs(noRoute).map((g) => [g.host, g.kind])).toContainEqual(["core2", "acl-uncollected"]);
    expect(T1_verdict(noRoute)).toMatch(/no ACLs collected for core2/);
    expect(claimBadge(noRoute)).not.toBe("SCOPED");
  });

  it("the T1 scope sentence never contradicts the trace's own ACL caveats — over every suggested flow", () => {
    // The class, not the two named cases: any trace whose caveats say a host's ACLs were not
    // collected must not claim that no filtering question was left unobserved.
    for (const s of suggestedFlows()) {
      const t = traceFlow(s.flow);
      const uncollected = t.caveats.filter((c) => /No ACLs were collected for/.test(c));
      if (uncollected.length > 0) expect(T1_verdict(t), s.id).not.toMatch(/no filtering question on this path was left unobserved/);
    }
  });

  it("a delivery at a host whose ACLs WERE collected and decide nothing against it stays definite", () => {
    // 10.0.10.50 -> 10.0.20.10 tcp/22: delivered at core1 out Vlan20. Vlan10 in and Vlan20 out were
    // observed with no access-group (VOICE_FILTER is bound INBOUND on Vlan20), so no list applies.
    const t = traceFlow(tcp("10.0.10.50", "10.0.20.10", 22));
    expect(t.outcome).toBe("delivered");
    expect(t.caveats.join(" ")).toMatch(/none is bound to the interfaces this flow enters \(Vlan10\) or leaves \(Vlan20\)/);
    /* UPDATED 2026-09-22 (auditor, B1): the connected Vlan20 route was chosen from core1's table,
       which the snapshot shows incomplete, so the modelled path is not decided on this snapshot
       either; the ingress is still assumed. The definite-on-path case runs in engine.counterfactual.test.ts. */
    expect(isDefiniteOnModelledPath(t)).toBe(false);
    expect(unobservedPolicyInputs(t).map((g) => g.kind).sort()).toEqual(["ingress-alternate", "ingress-port-unobserved", "rib-partial"]);
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).toBe("PARTIAL");
  });

  it("a router's own address is refused as router-originated, never a SCOPED or decided result", () => {
    /* 2026-09-22 auditor (B2): 10.0.30.1 is core1's own Vlan30 address. This test used to assert it
       was SCOPED — that was the defect: a packet core1 originates never arrives inbound on Vlan30, so
       neither that interface's inbound list nor a "gateway port" applies to it. The SCOPED ceiling is
       now exercised on a host address with complete tables in engine.counterfactual.test.ts. */
    const t = traceFlow(tcp("10.0.30.1", "10.0.20.10", 22));
    expect(refusalOf(t)?.kind).toBe("router-originated");
    expect(t.hops).toEqual([]);
    expect(t.outcome).toBe("indeterminate");
    expect(claimBadge(t)).not.toBe("SCOPED");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(t.claim).toMatch(/an address of core1 itself/);
  });

  it("no source in any device's own address set is ever decided — SVI, FHRP virtual, or RIB local /32 (sweep)", () => {
    /* The class, not the reported address: every address a collected device owns, read from the
       compiled evidence, against a destination grid. */
    const owned = new Set<string>();
    for (const r of fabric.l3) {
      const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
      if (a !== null) owned.add(formatIpv4(a.ip));
      if (r.vip !== null) owned.add(r.vip);
    }
    for (const rs of Object.values(fabric.routes))
      for (const r of rs) if (r.source === "local" && r.prefix.endsWith("/32")) owned.add(r.prefix.slice(0, -3));
    expect(owned.size).toBeGreaterThan(3);
    let n = 0;
    for (const src of owned)
      for (const dst of ["10.0.10.50", "10.0.20.50", "10.0.30.10", "10.0.40.50", "8.8.8.8"])
        for (const f of [tcp(src, dst, 443), tcp(src, dst, 22), udp(src, dst, 53)]) {
          const t = traceFlow(f);
          const label = JSON.stringify(f);
          expect(claimBadge(t), label).not.toBe("SCOPED");
          expect(["RESOLVED", "REFUTED"], label).not.toContain(bandOfTrace(t));
          expect(t.hops, `${label} was walked from a device's own address`).toEqual([]);
          n += 1;
        }
    expect(n).toBeGreaterThan(0);
  });

  it("over a sweep, no SCOPED trace rests on an ingress the trace's own caveat calls not a guarantee", () => {
    /* The class, not the reported flow: every trace whose caveat says the flow "may enter via" / "may
       instead enter via" another host must carry an ingress gap unless that alternate reproduced it,
       and no trace that carries one may be SCOPED. */
    const srcs = ["10.0.10.50", "10.0.10.77", "10.0.20.50", "10.0.30.50", "10.0.40.50", "10.0.10.1", "10.0.20.1", "10.0.30.1"];
    const dsts = ["10.0.10.10", "10.0.20.10", "10.0.30.10", "8.8.8.8", "10.0.40.10"];
    let checked = 0;
    for (const s of srcs)
      for (const d of dsts)
        for (const p of [22, 443, 3389]) {
          const t = traceFlow(tcp(s, d, p));
          const gaps = unobservedPolicyInputs(t);
          if (gaps.some((g) => g.kind === "ingress-alternate" || g.kind === "ingress-port-unobserved")) {
            checked += 1;
            expect(claimBadge(t), JSON.stringify(t.flow)).not.toBe("SCOPED");
            expect(isDefiniteDelivery(t), JSON.stringify(t.flow)).toBe(false);
          }
          if (claimBadge(t) === "SCOPED") expect(t.caveats.some((c) => /may (instead )?enter via/.test(c)), JSON.stringify(t.flow)).toBe(false);
        }
    expect(checked).toBeGreaterThan(20);
  });

  it("a delivery into Vlan10 is NOT definite: an access port there has an unnamed outbound ACL", () => {
    /* This used to be the "stays definite" case. It was definite only because the engine ignored
       the bindings: Gi1/0/5 (Vlan10) has an outbound access-group the collector did not name, and
       10.0.10.10's attachment port was never observed, so that port could be where it lives. */
    const t = traceFlow(udp("10.0.30.50", "10.0.10.10", 53));
    expect(isDefiniteDelivery(t)).toBe(false);
    expect(claimBadge(t)).not.toBe("SCOPED");
    expect(t.hops.flatMap((h) => h.evidence).some((e) => e.kind === "absence" && e.cite === "interfaces.core1.Gi1/0/5")).toBe(true);
  });
});

describe("denied — the blocking-hop answer", () => {
  // Same pair, a port PROTECT_SERVERS does not permit: it falls through to the explicit deny.
  const flow = tcp("10.0.10.50", "10.0.30.10", 3389);
  const trace = traceFlow(flow);

  it("names host, ACL, line index and the literal configuration line", () => {
    expect(trace.outcome).toBe("denied");
    const blocked = blockingHop(trace);
    expect(blocked).not.toBeNull();
    expect(blocked!.hop.host).toBe("core1");
    expect(blocked!.hop.verdict).toBe("denied");
    expect(blocked!.evidence.kind).toBe("acl");
    expect(blocked!.evidence.cite).toBe("acls.core1.PROTECT_SERVERS[3]");
    expect(blocked!.evidence.raw).toBe("deny ip any any");
    expect(blocked!.evidence.label).toContain("PROTECT_SERVERS");
    // 1-based, with the list length: the 0-based record index lives only in the citation (A3).
    expect(blocked!.evidence.label).toContain("line 4 of 4");
    expect(blocked!.evidence.label).not.toMatch(/line 3\b/);
    expect(blocked!.evidence.label).toContain("core1");
  });

  it("is headlined as a denial, with no evidence item left undecided (A3)", () => {
    /* REGRESSION: headlined "INDETERMINATE — THE MODEL COULD NOT DECIDE THIS FLOW" over a "denied"
       chip, because the unbound INET_RETURN's unevaluable line was counted against the flow, and
       every trace said no binding was collected anywhere. PROTECT_SERVERS is bound OUT on Vlan30. */
    /* UPDATED 2026-09-21 (critic B1): the denial is decided by a BOUND list with no evidence item left
       undecided — but it is not SCOPED, because the ingress before the modelled path is assumed:
       traced from core2 (HSRP Standby) the flow is dropped, not denied. OBSERVED is the ceiling. */
    expect(claimBadge(trace)).toBe("PARTIAL");
    expect(scopeTuple(trace).indeterminateEvidence).toBe(0);
    /* UPDATED 2026-09-22 (auditor, B1): the egress to Vlan30 rests on core1's connected route from a
       table the snapshot shows incomplete, which is named as a routing gap too. */
    expect(unobservedPolicyInputs(trace).map((g) => g.kind).sort()).toEqual(["ingress-alternate", "ingress-port-unobserved", "rib-partial"]);
    expect(trace.claim).toContain("applied outbound on core1 Vlan30 (interfaces.core1.Vlan30)");
    expect(trace.caveats.join(" ")).not.toMatch(/binding was collected anywhere/);
    expect(trace.caveats.join(" ")).toMatch(/core1: 2 interface ACL bindings were observed/);
    expect(trace.caveats.join(" ")).toMatch(/1 port has an access-group whose ACL name the collector did not project \(Gi1\/0\/5/);
  });

  it("is not poisoned by the unevaluable icmp line above it, because protocol excludes it", () => {
    // acls.core1.PROTECT_SERVERS[2] is `permit icmp any 10.0.30.0 0.0.0.255 echo-reply` — the
    // snapshot marks it INDETERMINATE, but an icmp ACE cannot match a tcp packet.
    expect(trace.claim).toMatch(/denied/);
    expect(trace.caveats.join(" ")).toContain("PROTECT_SERVERS");
  });

  it("offers no counterexample on this snapshot: every nearby delivery rests on an incomplete table", () => {
    /* UPDATED 2026-09-22 (auditor, B1): a counterexample must be a definite delivery on its modelled
       path, and on this snapshot every candidate at core1 is delivered on a route chosen from a table
       the snapshot shows incomplete. Nothing is offered, and the reason says the search ran. The
       offered-counterexample branch runs in engine.counterfactual.test.ts. */
    const cx = counterexample(flow, trace);
    expect(cx.found).toBe(false);
    if (cx.found) return;
    expect(cx.reason).toMatch(/nearby variations/);
  });

  it("a denial by a heuristically selected list is never SCOPED", () => {
    /* A denial decided by the list the specificity rule chose is what that list WOULD do, not
       evidence that it is applied here. The rule runs only where a binding is unknown: for icmp to
       10.0.10.1 the packet leaves by Vlan10, whose access port Gi1/0/5 has an unnamed outbound
       access-group. The unknown binding is itself an undecided input, so the badge falls below
       OBSERVED, to INDETERMINATE. */
    /* UPDATED 2026-09-21: icmp to 10.0.10.1 stays inside 10.0.10.0/24 and is no longer routed (it
       is reported as not modelled). icmp to an off-fabric address leaves core1 the same way and is
       denied by the same heuristically selected list. */
    const t = traceFlow({ srcIp: "10.0.10.50", dstIp: "8.8.8.8", protocol: "icmp", dstPort: null, srcPort: null });
    expect(t.outcome).toBe("denied");
    expect(unobservedPolicyInputs(t).map((g) => g.kind)).toContain("acl-unbound-denial");
    expect(claimBadge(t)).not.toBe("SCOPED");
    expect(T1_verdict(t)).toMatch(/no access-group binding for the denying list at core1/);
  });

  it("no longer offers the core2 delivery as a counterexample to the core2 drop", () => {
    /* REGRESSION: this drop used to be answered with tcp 10.0.20.50 -> 10.0.10.10:443 "DELIVERED",
       rendered SCOPED, although core2 has no collected ACL. */
    const dropFlow = tcp("10.0.20.50", "198.51.100.7", 443);
    const dropped = traceFlow(dropFlow);
    expect(dropped.outcome).toBe("dropped");
    const cx = counterexample(dropFlow, dropped);
    /* Asserted unconditionally. Both checks used to sit behind `if (cx.found)`, so on the branch
       that is actually current — no counterexample at all — only `dropped.outcome` was checked and
       the test could not fail. It now pins that nothing is offered, AND that this is because the
       variations at core2 were searched and none was a definite delivery: an early exit such as
       "no blocking hop was recorded" would also read `found: false` while having searched nothing. */
    expect(cx.found).toBe(false);
    if (cx.found) return; // narrows the union for the reason check below; unreachable after the line above
    expect(cx.reason).toMatch(/nearby variations derived from the evidence at core2/);
    expect(cx.reason).toMatch(/not proof that none exists/);
  });

  /* "any counterexample it does offer is a definite delivery", the two citation tests and the
     citation sweep moved to engine.counterfactual.test.ts: on this snapshot no counterexample is offered at all (see above),
     so here they could only pass vacuously. */
});

describe("indeterminate — an ACL line we cannot evaluate", () => {
  it("refuses to decide an icmp flow that the echo-reply line could match", () => {
    const trace = traceFlow({
      srcIp: "10.0.10.50",
      dstIp: "10.0.30.10",
      protocol: "icmp",
      dstPort: null,
      srcPort: null,
    });
    expect(trace.outcome).toBe("indeterminate");
    expect(trace.caveats.join(" ")).toContain("acls.core1.PROTECT_SERVERS[2]");
    expect(trace.claim).not.toMatch(/\bis delivered\b/);
  });

  it("refuses to decide an internet-bound tcp flow behind `permit tcp any any established`", () => {
    const trace = traceFlow(tcp("10.0.10.50", "203.0.113.9", 443));
    expect(trace.outcome).toBe("indeterminate");
    expect(trace.caveats.join(" ")).toContain("acls.core1.INET_RETURN[0]");
  });
});

describe("unmodelled forwarding is never delivery", () => {
  // 10.0.40.0/24 is dist1's Vlan40 SVI subnet (l3_forwarding[5]); no RIB was collected for dist1.
  const trace = traceFlow(tcp("10.0.40.50", "10.0.30.10", 443));

  it("stops at the host whose forwarding table we do not hold", () => {
    expect(trace.outcome).toBe("indeterminate");
    expect(trace.outcome).not.toBe("delivered");
    expect(trace.unmodelledHosts).toContain("dist1");
    const hop = trace.hops.find((h) => h.host === "dist1")!;
    expect(hop.verdict).toBe("unmodeled");
    expect(hop.decidedBy?.kind).toBe("absence");
    expect(hop.decidedBy?.raw).toBeNull();
  });

  it("says so in the claim rather than implying a clean path", () => {
    expect(trace.claim).toMatch(/dist1/);
    expect(trace.claim.toLowerCase()).toMatch(/cannot|not collected|no .*routing table/);
  });
});

describe("no route is a drop, and it cites the RIB it searched", () => {
  // core2 is Vlan20's HSRP active gateway and carries NO default route.
  const trace = traceFlow(tcp("10.0.20.50", "203.0.113.9", 443));

  it("drops with an absence citation naming the searched RIB", () => {
    expect(trace.hops[0]!.host).toBe("core2");
    expect(trace.outcome).toBe("dropped");
    expect(trace.hops[0]!.verdict).toBe("no-route");
    expect(trace.hops[0]!.decidedBy?.kind).toBe("absence");
    expect(trace.hops[0]!.decidedBy?.label).toContain("core2");
  });

  it("does not let core2's missing ACL collection read as 'unfiltered'", () => {
    expect(trace.caveats.join(" ")).toMatch(/core2/);
    expect(trace.caveats.join(" ")).toMatch(/no ACL|not collected/i);
  });
});

describe("out of scope", () => {
  it("refuses to invent an ingress for a source address in no observed subnet", () => {
    const trace = traceFlow(tcp("198.51.100.7", "10.0.30.10", 443));
    expect(trace.outcome).toBe("out-of-scope");
    expect(trace.hops).toEqual([]);
    expect(trace.claim).toContain("198.51.100.7");
    expect(trace.caveats.length).toBeGreaterThan(0);
  });

  it("refuses malformed input instead of coercing it into a trace", () => {
    const trace = traceFlow(tcp("10.0.10.999", "10.0.30.10", 443));
    expect(trace.outcome).toBe("out-of-scope");
    expect(trace.hops).toEqual([]);
    expect(trace.claim.toLowerCase()).toContain("not a valid");
  });
});

describe("ACL evaluability is decided structurally, not from a list of known keywords", () => {
  it("agrees with every qualifier finding the snapshot itself raised", () => {
    const snapshotFlagged = fabric.aclFindings.filter(
      (f) => f.detail !== null && !f.detail.includes("an earlier unevaluable line"),
    );
    expect(snapshotFlagged.length).toBeGreaterThan(0);
    for (const f of snapshotFlagged) {
      const lines = fabric.acls[f.host ?? ""]?.[f.acl ?? ""] ?? [];
      const line = lines.find((l) => l.index === f.lineIndex);
      expect(line, f.cite).toBeDefined();
      expect(lineEvaluability(line!).evaluable, `${f.cite} ${f.raw}`).toBe(false);
    }
  });

  /* AMENDED 2026-09-21. This test originally used core1/MGMT_IN[0] as its example of an
     unresolvable group. The compiler now emits `objectGroups`, so MGMT_HOSTS resolves and that
     line is evaluable — see "a carried object-group resolves" below. The requirement being tested
     here is unchanged and still load-bearing: a group we genuinely cannot resolve must be
     unevaluable, derived structurally rather than from a list of known keywords. It just needs an
     example that is actually unresolvable, so the test asserts the rule rather than the fixture. */
  it("treats an unresolvable object-group as unevaluable even though the snapshot did not flag it", () => {
    const line: AclLine = {
      index: 0,
      action: "permit",
      raw: "permit tcp object-group NOT_IN_THIS_SNAPSHOT any eq 22",
      proto: "tcp",
      src: { ip: null, wild: null, group: "NOT_IN_THIS_SNAPSHOT" },
      dst: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      sport: null,
      dport: { op: "eq", val: 22 },
      unevaluable: false, // deliberately NOT flagged: the guard must be structural
      unmodeledQualifiers: [],
      established: false,
      icmpType: null,
      timeRange: null,
      cite: "acls.core1.SYNTHETIC[0]",
    };
    expect(resolveObjectGroup("core1", "NOT_IN_THIS_SNAPSHOT")).toBeNull();
    expect(lineEvaluability(line).evaluable).toBe(false);
    expect(lineEvaluability(line).reason).toMatch(/object-group/);
  });

  it("holds a CARRIED object-group evaluable, and resolves its member space", () => {
    /* The other half of the same rule. MGMT_HOSTS is present in the snapshot with two members, one
       of which (10.0.40.0/24) is a real VLAN in this fabric. Once the compiler carries the group,
       refusing to evaluate the line would understate what our evidence actually supports — the
       mirror-image error of overclaiming, and just as much a misreport of coverage. */
    const line = fabric.acls["core1"]!["MGMT_IN"]![0]!;
    expect(line.src?.group).toBe("MGMT_HOSTS");
    expect(lineEvaluability(line).evaluable).toBe(true);

    const dst = parseIpv4("10.0.30.10")!;
    const inGroup = tcp("10.0.40.7", "10.0.30.10", 22);
    const outOfGroup = tcp("10.0.10.50", "10.0.30.10", 22);
    expect(matchTri(line, inGroup, parseIpv4("10.0.40.7")!, dst)).toBe("yes");
    expect(matchTri(line, outOfGroup, parseIpv4("10.0.10.50")!, dst)).toBe("no");
  });

  it("will not rule a flow OUT on a group it only partly understands", () => {
    // A single unparseable member makes the whole group "maybe": ruling something out on
    // incomplete evidence is how a permit silently becomes a deny.
    const line: AclLine = {
      index: 0,
      action: "permit",
      raw: "permit tcp object-group MGMT_HOSTS any eq 22",
      proto: "tcp",
      src: { ip: null, wild: null, group: "MGMT_HOSTS" },
      dst: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      sport: null,
      dport: { op: "eq", val: 22 },
      unevaluable: false,
      unmodeledQualifiers: [],
      established: false,
      icmpType: null,
      timeRange: null,
      cite: "acls.core1.MGMT_IN[0]",
    };
    // 203.0.113.9 is in neither member, and both members parse, so "no" is justified here.
    expect(matchTri(line, tcp("203.0.113.9", "10.0.30.10", 22), parseIpv4("203.0.113.9")!, parseIpv4("10.0.30.10")!)).toBe("no");
  });

  it("holds plain address/port lines evaluable", () => {
    const line = fabric.acls["core1"]!["PROTECT_SERVERS"]![0]!;
    expect(lineEvaluability(line).evaluable).toBe(true);
    expect(lineEvaluability(fabric.acls["core1"]!["PROTECT_SERVERS"]![3]!).evaluable).toBe(true);
  });
});

describe("suggested flows", () => {
  const flows = suggestedFlows();

  it("offers a set of genuinely different outcomes derived from the data", () => {
    expect(flows.length).toBeGreaterThanOrEqual(4);
    const outcomes = new Set(flows.map((f) => f.expectedOutcome));
    expect(outcomes.size).toBeGreaterThanOrEqual(4);
    for (const f of flows) expect(f.rationale.length).toBeGreaterThan(10);
  });

  it("advertises the outcome the engine actually produces", () => {
    for (const f of flows) {
      expect(traceFlow(f.flow).outcome, `${f.id} ${JSON.stringify(f.flow)}`).toBe(f.expectedOutcome);
    }
  });

  it("never produces an unqualified claim: caveats are non-empty for every one", () => {
    for (const f of flows) {
      const t = traceFlow(f.flow);
      expect(t.caveats.length, `${f.id} has no caveats`).toBeGreaterThan(0);
    }
  });

  /* REGRESSION — this test used to assert a three-octet STRING PREFIX match, which is not a
     membership test: "10.0.4" is a string prefix of the observed "10.0.40.2", so an address the
     snapshot never saw satisfied it. Meanwhile the builder really does synthesise two sources with
     hostAddressIn(), so the property the test NAMED was false while the test passed. The engine now
     labels each source, and this checks the label against the evidence with exact membership. */
  it("labels every suggested source as observed or derived, and each label is true", () => {
    const observed = new Set<string>();
    for (const e of fabric.endpoints) if (e.ip !== null) observed.add(e.ip);
    for (const r of fabric.l3) {
      if (r.sviIp !== null) {
        const a = parseInterfaceAddress(r.sviIp);
        if (a !== null) observed.add(formatIpv4(a.ip));
      }
      if (r.vip !== null) observed.add(r.vip);
    }
    // Guard the guard: exact membership, so the two addresses that defeated the old predicate fail.
    expect(observed.has("10.0.10.50")).toBe(true);
    expect(observed.has("10.0.4.77")).toBe(false);
    expect(observed.has("10.0.1.1")).toBe(false);

    // Every provenance cite must name a record that exists in the compiled model. Checked against
    // the records' own `cite` values rather than through resolveCite: endpoint and l3 cites are
    // paths into the SOURCE snapshot's coordinate space, which resolveCite does not walk.
    const knownCites = new Set<string>([
      ...fabric.endpoints.map((e) => e.cite),
      ...fabric.l3.map((r) => r.cite),
      fabric.coverage.cite,
    ]);
    for (const f of flows) {
      const p = f.srcProvenance;
      expect(knownCites.has(p.cite), `${f.id} cites ${p.cite}, which names no record`).toBe(true);
      if (p.kind === "observed") {
        expect(observed.has(f.flow.srcIp), `${f.id} claims ${f.flow.srcIp} was observed`).toBe(true);
      } else if (p.kind === "derived-from-observed-subnet") {
        const subnet = fabric.l3.find((r) => r.cite === p.cite);
        expect(subnet?.sviIp, `${f.id} cites ${p.cite} as a subnet`).toBeDefined();
        const prefix = parseInterfaceAddress(subnet!.sviIp!)!.prefix;
        const ip = parseIpv4(f.flow.srcIp)!;
        expect(prefixContains(prefix, ip), `${f.id} src is outside its cited subnet`).toBe(true);
        expect(addressRoleIn(prefix, ip), `${f.id} src is not a host address`).toBe("host");
        expect(p.note).toContain("not itself observed");
      } else {
        expect(traceFlow(f.flow).outcome, `${f.id} claims to be off-fabric`).toBe("out-of-scope");
      }
    }
    // Both live branches must actually occur, or this test is checking a case that never arises.
    const kinds = new Set(flows.map((f) => f.srcProvenance.kind));
    expect(kinds.has("observed")).toBe(true);
    expect(kinds.has("derived-from-observed-subnet")).toBe(true);
  });
});

describe("no hop reads as success inside a result that is not one", () => {
  // The false-health class: a hop chip rendered "delivered" while the trace says it could not be
  // decided. Checked across every flow the module offers plus the awkward hand-built ones.
  const probes: Flow[] = [
    ...suggestedFlows().map((s) => s.flow),
    tcp("10.0.10.50", "10.0.30.10", 443),
    tcp("10.0.10.50", "10.0.40.10", 443),
    { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: null, srcPort: null },
    { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "ip", dstPort: null, srcPort: null },
    { srcIp: "10.0.10.1", dstIp: "10.0.20.10", protocol: "tcp", dstPort: 22, srcPort: null },
    { srcIp: "10.0.20.50", dstIp: "10.0.30.10", protocol: "udp", dstPort: 5060, srcPort: null },
  ];

  it("only marks a hop delivered when the whole trace is delivered", () => {
    for (const f of probes) {
      const t = traceFlow(f);
      const delivered = t.hops.filter((h) => h.verdict === "delivered");
      if (t.outcome === "delivered") {
        expect(delivered.length, JSON.stringify(f)).toBe(1);
      } else {
        expect(delivered, `${JSON.stringify(f)} -> ${t.outcome}`).toEqual([]);
      }
    }
  });

  it("gives every hop a decidedBy, and every claim a citation", () => {
    for (const f of probes) {
      const t = traceFlow(f);
      for (const h of t.hops) {
        expect(h.decidedBy, `${JSON.stringify(f)} hop ${h.index}`).not.toBeNull();
        expect(h.decidedBy!.cite.length).toBeGreaterThan(0);
      }
      expect(t.claim.length, JSON.stringify(f)).toBeGreaterThan(40);
    }
  });

  it("never lets an uncollected RIB or unevaluable line read as a clean path", () => {
    /* Every probe is judged (the implication, stated per flow), and the antecedent's population is
       pinned: the first version asserted only inside `if (unmodelledHosts.length > 0)`, which on
       this snapshot held for 1 probe of 11, so a change that emptied it would have left a test that
       runs, passes and checks nothing. */
    let exercised = 0;
    for (const f of probes) {
      const t = traceFlow(f);
      if (t.unmodelledHosts.length > 0) exercised += 1;
      expect(
        t.unmodelledHosts.length === 0 || t.outcome === "indeterminate",
        `${JSON.stringify(f)}: unmodelled ${t.unmodelledHosts.join(", ")} but outcome ${t.outcome}`,
      ).toBe(true);
    }
    expect(probes.length, "the probe set").toBeGreaterThan(5);
    expect(exercised, "probes whose trace crosses an unmodelled host (the case this test is about)").toBeGreaterThan(0);
  });
});

describe("ACLs that were NOT applied are reported as unknown, not as absent", () => {
  it("names MGMT_IN, whose object-group could never be scored, on a core1 trace that fell back", () => {
    // A hop with an unknown binding (Gi1/0/5 out) — the only place "not applied" is a heuristic.
    const t = traceFlow(tcp("10.0.30.50", "10.0.10.77", 443));
    const joined = t.caveats.join(" ");
    expect(joined).toContain("MGMT_IN");
    expect(joined).toMatch(/not evidence/i);
  });

  it("where every binding was observed, an unbound list is stated as not filtering, with the interfaces named", () => {
    const joined = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443)).caveats.join(" ");
    expect(joined).toMatch(/core1 also defines INET_RETURN, MGMT_IN, VOICE_FILTER, bound to none of the interfaces this flow crosses at core1 \(Vlan10 in, Vlan30 out/);
  });
});

/* ── the three claim-honesty defects found by an external audit, 2026-09-21 ───────────────────
   Each of these was a positive claim the code asserted rather than measured. They are pinned
   here against the REAL compiled snapshot, not a fixture, because each one was true-looking and
   wrong on the app's own headline flow. */
describe("undecidability is a property of the deciding HOST, not of the ACL the heuristic picked", () => {
  /* Scoped to the FALLBACK (no binding consulted — the evaluateAcls unit seam, which is exactly what
     a hop with an unknown binding runs). Where the bindings are observed the heuristic does not
     pick at all; see "a permit that steps over an undecidable line" above. */
  const headline = tcp("10.0.10.50", "10.0.30.10", 443);
  const src = parseIpv4("10.0.10.50")!;
  const dst = parseIpv4("10.0.30.10")!;

  it("the preconditions this test rests on are the real ones", () => {
    // If these change, the assertions below stop meaning what they say.
    const inet = fabric.acls["core1"]?.["INET_RETURN"] ?? [];
    expect(lineEvaluability(inet[0]!).evaluable).toBe(false);
    expect(lineEvaluability(inet[1]!).evaluable).toBe(false);
    expect(matchTri(inet[0]!, headline, parseIpv4("10.0.10.50")!, parseIpv4("10.0.30.10")!)).toBe("yes");
    expect(matchTri(inet[1]!, headline, parseIpv4("10.0.10.50")!, parseIpv4("10.0.30.10")!)).toBe("yes");
  });

  it("a line in a NON-selected ACL that could match and cannot be decided is emitted as undecided evidence", () => {
    const r = evaluateAcls("core1", headline, src, dst);
    const cites = r.evidence.map((e) => String(e.cite));
    expect(cites).toContain("acls.core1.INET_RETURN[0]");
    expect(cites).toContain("acls.core1.INET_RETURN[1]");
    expect(r.evidence.filter((e) => e.kind === "absence").length).toBeGreaterThan(0);
  });

  it("the matching applied line stays listed first, but it no longer decides a permit on its own", () => {
    const r = evaluateAcls("core1", headline, src, dst);
    expect(r.verdict).toBe("indeterminate");
    expect(String(r.evidence.find((e) => e.kind === "acl")?.cite)).toBe("acls.core1.PROTECT_SERVERS[0]");
    expect(String(r.decidedBy?.cite)).toBe("acls.core1.INET_RETURN[0]");
  });

  it("with the hop's OBSERVED bindings, the unbound list cannot decide it (A3)", () => {
    const r = evaluateAcls("core1", headline, src, dst, undefined, { ingress: "Vlan10", egress: "Vlan30" });
    expect(r.bindingMode).toBe("observed");
    expect(r.verdict).toBe("permit");
    expect(String(r.decidedBy?.cite)).toBe("acls.core1.PROTECT_SERVERS[0]");
    expect(r.evidence.map((e) => e.cite)).not.toContain("acls.core1.INET_RETURN[0]");
  });
});

describe("the not-applied caveat MEASURES its claim about each discarded list", () => {
  it("names the specific undecidable line instead of calling it a catch-all", () => {
    const joined = evaluateAcls("core1", tcp("10.0.10.50", "10.0.30.10", 443), parseIpv4("10.0.10.50")!, parseIpv4("10.0.30.10")!).caveats.join(" ");
    expect(joined).toContain("acls.core1.INET_RETURN[1]");
    expect(joined).toMatch(/INET_RETURN \(matches this flow at acls\.core1\.INET_RETURN\[1\]/);
  });

  it("says 'only through catch-all lines' ONLY where every matching line really is any/any", () => {
    // VOICE_FILTER's only line reachable by this flow is `deny ip any any`; MGMT_IN's is the same.
    // The phrase is allowed there and nowhere else, so every emission of it is re-derived.
    /* Both places a reader meets the phrase are read: the whole trace, AND the fallback seam
       (`evaluateAcls` with no binding — what a hop with an unknown binding runs), which is where it
       is emitted on this snapshot. The first version read `traceFlow` alone; with the bindings now
       observed on core1 the trace never takes the fallback, so the loop over emissions was empty and
       the test ran, passed and made ZERO assertions (found by the runtime assertion guard,
       src/test-setup.ts). The emissions are now counted and the lists that earn the phrase pinned. */
    const named = new Set<string>();
    for (const flow of [tcp("10.0.10.50", "10.0.30.10", 443), tcp("10.0.10.50", "10.0.30.10", 22), tcp("10.0.10.50", "10.0.30.10", 3389)]) {
      const fallback = evaluateAcls("core1", flow, parseIpv4(flow.srcIp)!, parseIpv4(flow.dstIp)!).caveats;
      const caveats = [...traceFlow(flow).caveats, ...fallback].join(" ");
      for (const m of caveats.matchAll(/(\w+) \(matches this flow only through catch-all lines\)/g)) {
        const name = m[1]!;
        named.add(name);
        const lines = fabric.acls["core1"]?.[name] ?? [];
        const src = parseIpv4(flow.srcIp)!;
        const dst = parseIpv4(flow.dstIp)!;
        const matching = lines.filter((l) => matchTri(l, flow, src, dst) !== "no");
        expect(matching.length).toBeGreaterThan(0);
        for (const l of matching) expect(l.raw).toMatch(/\bany\s+any\b/);
      }
    }
    // Known answer: the two lists the comment above names, and only lists that really are catch-all.
    expect([...named].sort(), "lists the phrase was emitted for").toEqual(["MGMT_IN", "VOICE_FILTER"]);
  });
});

describe("no suggestion claims uniqueness it did not count", () => {
  it("no rationale contains an unquantified uniqueness word", () => {
    for (const s of suggestedFlows()) {
      expect(s.rationale).not.toMatch(/\bit is the (one|only)\b/i);
      expect(s.rationale).not.toMatch(/\bthe only (shape|flow|traffic)\b/i);
    }
  });

  it("and the claim would have been false: more than one flow ends in delivery", () => {
    // UPDATED: flows into core1's 10.0.30.0/24 now trace indeterminate (they step over INET_RETURN[0]),
    // so this counts definite deliveries at core2 instead — the uniqueness point is unchanged.
    const delivered = [22, 443, 3389]
      .flatMap((p) => ["10.0.10.10", "10.0.20.10"].map((d) => tcp("10.0.20.10", d, p)))
      .map((f) => traceFlow(f))
      .filter((t) => t.outcome === "delivered");
    expect(delivered.length).toBeGreaterThan(1);
  });
});

describe("every verdict names the RIB scope in the SENTENCE, not only in the caveats", () => {
  it("including the out-of-scope outcomes, which used to omit it", () => {
    const flows: Flow[] = [
      ...suggestedFlows().map((s) => s.flow),
      tcp("198.51.100.7", "10.0.30.10", 443),
      { srcIp: "10.0.30.0", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null },
      { srcIp: "not-an-ip", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null },
    ];
    const scope = `${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length}`;
    for (const f of flows) {
      const t = traceFlow(f);
      expect(t.claim, `${t.outcome}: ${t.claim}`).toContain(scope);
    }
  });
});

describe("determinism and budget", () => {
  const flow = tcp("10.0.10.50", "10.0.30.10", 3389);

  it("produces byte-identical results for the same flow, twice", () => {
    const a = traceFlow(flow);
    const b = traceFlow(flow);
    const strip = (t: ReturnType<typeof traceFlow>) => JSON.stringify({ ...t, elapsedMs: 0 });
    expect(strip(a)).toBe(strip(b));
  });

  /**
   * A STRUCTURAL bound, not a clock (acceptance F2 / O26).
   *
   * These two tests used to take the median of 7 wall-clock runs against a 50 ms tripwire. A unit
   * test does not control the machine: under multi-agent load the counterexample median measured
   * 54.66 ms for a search that takes a few milliseconds on a quiet host, and a red that means "the
   * host was busy" cannot be told from one that means "someone made this quadratic". Time budgets are
   * measured against the running application by the E harnesses (`review/measure-inp.mjs` and
   * friends), which label themselves laboratory.
   *
   * What survives here is the thing a unit test can honestly assert on any machine: how much WORK
   * the engine does, in its own units (`engineWork()`). A trace runs at most one trace per ingress
   * candidate of its source (itself plus one memoised trace per alternate, which cannot recurse), at
   * most TTL_LIMIT hop iterations per trace, and asks the matcher about each ACL line on a hop at most
   * ACL_PASSES_PER_HOP times. `engine.work-bound.test.ts` sweeps the same bounds over the whole flow
   * space and over long lists; the timing is still measured and REPORTED, never asserted.
   */
  it("does not blow up algorithmically on any suggested flow (work, not wall clock)", async ({ annotate }) => {
    const maxLines = Math.max(0, ...Object.values(fabric.acls).map((named) => Object.values(named).reduce((n, ls) => n + ls.length, 0)));
    const timings: string[] = [];
    for (const f of suggestedFlows()) {
      const src = parseIpv4(f.flow.srcIp);
      const perRequest = Math.max(1, src === null ? 0 : ingressCandidates(src).length);
      const before = engineWork();
      const t = traceFlow(f.flow);
      const after = engineWork();
      const traces = after.traces - before.traces;
      const hops = after.hops - before.hops;
      expect(traces, `${f.id}: traces vs ${perRequest} ingress candidates`).toBeGreaterThanOrEqual(1);
      expect(traces, `${f.id}: traces vs ${perRequest} ingress candidates`).toBeLessThanOrEqual(perRequest);
      expect(hops, `${f.id}: hop iterations`).toBeLessThanOrEqual(traces * TTL_LIMIT);
      expect(after.lineMatches - before.lineMatches, `${f.id}: ACL line matches`).toBeLessThanOrEqual(hops * ACL_PASSES_PER_HOP * maxLines);
      timings.push(`${f.id} ${t.elapsedMs.toFixed(2)} ms`);
    }
    await annotate(`single-run trace times (reported, not asserted): ${timings.join(", ")}`);
  });

  it("keeps the counterexample search inside its candidate budget (work, not wall clock)", async ({ annotate }) => {
    /* The UI asks for a counterexample in the same gesture that runs the trace, so its cost is part
       of that interaction. Its budget is COUNTEREXAMPLE_CANDIDATE_CAP candidates, each traced once
       (plus, the first time, its memoised alternate-ingress traces). */
    const t = traceFlow(flow);
    const src = parseIpv4(flow.srcIp)!;
    const perRequest = Math.max(1, ingressCandidates(src).length);
    const before = engineWork();
    const started = performance.now();
    const cx = counterexample(flow, t);
    const ms = performance.now() - started;
    const w = engineWork();
    /* The search ran (its reason says so) and found nothing definite on this snapshot; the found
       branch runs in engine.counterfactual.test.ts. */
    expect(cx.found).toBe(false);
    if (cx.found) return;
    expect(cx.reason).toMatch(/nearby variations/);
    const considered = Number(/None of the (\d+) nearby variations/.exec(cx.reason)?.[1] ?? NaN);
    expect(considered).toBeGreaterThan(0);
    expect(considered).toBeLessThanOrEqual(COUNTEREXAMPLE_CANDIDATE_CAP);
    expect(w.traces - before.traces).toBeLessThanOrEqual(considered * perRequest);
    expect(w.hops - before.hops).toBeLessThanOrEqual((w.traces - before.traces) * TTL_LIMIT);
    await annotate(`counterexample: ${considered} candidates, ${w.traces - before.traces} traces, ${ms.toFixed(2)} ms (reported, not asserted)`);
  });

  it("gives the same counterexample every time", () => {
    const t = traceFlow(flow);
    const a = counterexample(flow, t);
    const b = counterexample(flow, t);
    expect(a.found && b.found ? JSON.stringify([a.flow, a.rationale]) : a).toEqual(
      b.found && a.found ? JSON.stringify([b.flow, b.rationale]) : b,
    );
  });

  /* REGRESSION — this used to read `expect(TTL_LIMIT).toBe(16)` plus `hops.length <= 16` over the
     suggested flows, and was presented as evidence the hop loop terminates. The first assertion
     asserts a constant; the second was evaluated only where hops.length is always 1. Measured over
     the reachable flow space, NO trace on this data takes a second hop, so the loop detector, the
     TTL cut, resolveNextHost's cable-map branch and chooseRoute's tie-break had zero executions.
     What follows ties the cap to the data, measures the real depth, and ratchets the gap. */
  it("caps the trace above the fabric's own depth rather than at a number written here", () => {
    expect(Number.isInteger(TTL_LIMIT)).toBe(true);
    expect(TTL_LIMIT).toBeGreaterThan(fabric.tiers.length);
    expect(TTL_LIMIT).toBeLessThan(256);
  });
});

describe("hop depth is measured, and the multi-hop machinery this data cannot reach is named", () => {
  const probeAddresses = (): string[] => {
    const out = new Set<string>(["10.0.30.10", "10.0.41.50", "198.51.100.7", "10.0.10.254", "10.0.30.254"]);
    for (const e of fabric.endpoints) if (e.ip !== null) out.add(e.ip);
    for (const r of fabric.l3) {
      if (r.sviIp !== null) {
        const a = parseInterfaceAddress(r.sviIp);
        if (a !== null) out.add(formatIpv4(a.ip));
      }
      if (r.vip !== null) out.add(r.vip);
    }
    return [...out].sort();
  };

  it("never exceeds the cap, and records the depth it actually reaches", () => {
    const addresses = probeAddresses();
    const depths = new Map<number, number>();
    let resolvedNextHops = 0;
    for (const src of addresses) {
      for (const dst of addresses) {
        for (const [protocol, ports] of [
          ["tcp", [null, 22, 443, 8443]],
          ["udp", [null, 5060, 20000]],
          ["icmp", [null]],
          ["ip", [null]],
        ] as const) {
          for (const dstPort of ports) {
            const t = traceFlow({ srcIp: src, dstIp: dst, protocol, dstPort, srcPort: null });
            expect(t.hops.length, `${src}->${dst}/${protocol}`).toBeLessThanOrEqual(TTL_LIMIT);
            depths.set(t.hops.length, (depths.get(t.hops.length) ?? 0) + 1);
            resolvedNextHops += t.hops.filter((h) => h.nextHost !== null).length;
          }
        }
      }
    }
    // A RATCHET, not a pass. Maximum observed depth on this snapshot is 1, so `visited`, the TTL
    // cut and every second-iteration path are UNCOVERED by this suite. Should this ever fail, the
    // data has gained a multi-hop path and those branches need real tests — not a raised bound.
    expect(Math.max(...depths.keys())).toBe(1);
    expect(resolvedNextHops).toBe(0);
  });

  it("explains that depth structurally: no collected route points at a collected host", () => {
    const owned = new Set<string>();
    for (const r of fabric.l3) {
      if (r.sviIp !== null) {
        const a = parseInterfaceAddress(r.sviIp);
        if (a !== null) owned.add(formatIpv4(a.ip));
      }
      if (r.vip !== null) owned.add(r.vip);
    }
    for (const host of fabric.coverage.routableHosts) {
      for (const r of routesOf(host)) {
        if (r.source !== "local") continue;
        const p = parsePrefix(r.prefix);
        if (p !== null && p.bits === 32) owned.add(formatIpv4(p.base));
      }
    }
    let nextHops = 0;
    for (const host of fabric.coverage.routableHosts) {
      const ports = new Set((linksByHost.get(host) ?? []).map((l) => (l.a === host ? l.aPort : l.bPort)));
      for (const r of routesOf(host)) {
        if (r.nextHop !== null) {
          nextHops += 1;
          expect(owned.has(r.nextHop), `${r.cite} points at ${r.nextHop}`).toBe(false);
        }
        // The same ratchet for resolveNextHost's cable-map fallback: no route names a cabled port.
        if (r.outIntf !== null) expect(ports.has(r.outIntf), `${r.cite} egress ${r.outIntf}`).toBe(false);
      }
    }
    expect(nextHops).toBeGreaterThan(0); // the premise is checked, not assumed
  });

  it("follows a real unresolvable next hop to an honest dead end rather than a drop", () => {
    const def = routesOf("core1").find((r) => r.prefix === "0.0.0.0/0")!;
    const next = resolveNextHost("core1", def);
    expect(next.host).toBeNull();
    expect(next.evidence).toBeNull();
    expect(next.caveat).toContain(def.nextHop!);
    expect(next.caveat).toMatch(/not a proven dead end/);
    // And the cable-map fallback really is inert here, with the host's real links passed in.
    expect(resolveNextHost("core1", { ...def, nextHop: null }, linksByHost.get("core1") ?? []).host).toBeNull();
  });

  it("breaks a prefix-length tie on administrative distance, using two real route records", () => {
    // core1 and core2 each carry a genuine `10.0.10.0/24 connected`. No single host in this
    // snapshot holds two routes of equal length, so this is the only way to run the tie-break on
    // records the collector actually produced rather than on a RIB invented here.
    const a = routesOf("core1").find((r) => r.prefix === "10.0.10.0/24")!;
    const b = routesOf("core2").find((r) => r.prefix === "10.0.10.0/24")!;
    expect(a.cite).not.toBe(b.cite);
    const choice = chooseRoute("core1", parseIpv4("10.0.10.50")!, [a, b]);
    expect(choice).not.toBeNull();
    expect(choice!.winner.prefix).toBe("10.0.10.0/24");
    expect(choice!.alternatives.map((r) => r.cite)).toEqual([b.cite]);
    expect(choice!.caveat).toMatch(/administrative distance/);
    expect(choice!.caveat).toContain("equal-cost paths were not explored");
    // Unchanged with the real RIB: one route wins outright and no tie caveat is manufactured.
    expect(chooseRoute("core1", parseIpv4("10.0.10.50")!)!.caveat).toBeNull();
  });
});

/* ── regressions: a field the model cannot read is never a definite answer ──── */

const SRC = parseIpv4("10.0.10.50")!;
const DST = parseIpv4("10.0.30.10")!;
const flowOn = (protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp: "10.0.10.50",
  dstIp: "10.0.30.10",
  protocol,
  dstPort,
  srcPort: null,
});

describe("an ACL port operand the collection did not resolve is unknown, not a non-match", () => {
  const citrix = compiled(PRODUCER.citrix, "PROBE", 0);
  const dynamic = compiled(PRODUCER.rangeDynamic, "PROBE", 0);

  /* REGRESSION — the producer emits {"op":"eq","val":null} for `eq citrix`, and the compiler drops
     its `unevaluable` flag. The evaluability guard compared only PRESENCE of the port field, so the
     line was declared evaluable; the matcher then evaluated `1494 === null` as a definite "no".
     The permit never fired, the flow fell to `deny ip any any`, and the engine answered "denied"
     with no indeterminacy caveat for traffic the configuration text explicitly permits. */
  it("refuses to evaluate a line whose port the producer could not resolve", () => {
    const ev = lineEvaluability(citrix);
    expect(ev.evaluable).toBe(false);
    expect(ev.reason).toMatch(/port/i);
    expect(ev.representative.dport).toBe(false);
    expect(ev.representative.src).toBe(true); // the dimensions it DID vouch for stay usable
  });

  it("does not let that line say no to the port it actually names", () => {
    expect(matchTri(citrix, flowOn("tcp", 1494), SRC, DST)).not.toBe("no");
    expect(matchTri(dynamic, flowOn("udp", 20000), SRC, DST)).not.toBe("no");
    // The dimensions the text check did vouch for still exclude what they genuinely exclude.
    expect(matchTri(citrix, flowOn("tcp", 1494), parseIpv4("192.0.2.1")!, DST)).toBe("no");
  });

  it("answers indeterminate, not denied, for a flow that line could permit", () => {
    for (const [line, flow] of [
      [citrix, flowOn("tcp", 1494)],
      [dynamic, flowOn("udp", 20000)],
    ] as const) {
      const named = { PROBE: [line, compiled(PRODUCER.denyAll, "PROBE", 1)] };
      const acl = evaluateAcls("core1", flow, SRC, DST, named);
      expect(acl.verdict, line.raw!).toBe("indeterminate");
      expect(acl.decidedBy?.cite).toBe("acls.core1.PROBE[0]");
      expect(acl.caveats.join(" ")).toContain("no verdict below it can be proven");
    }
  });

  it("refuses an unmodelled port operator on the same structural ground", () => {
    const odd: AclLine = { ...citrix, dport: { op: "lte", val: 1494 } };
    expect(lineEvaluability(odd).evaluable).toBe(false);
    expect(lineEvaluability(odd).reason).toMatch(/operator/i);
    expect(matchTri(odd, flowOn("tcp", 9999), SRC, DST)).not.toBe("no");
  });
});

describe("a port list is not evaluated as the one port the model kept", () => {
  const portList = compiled(PRODUCER.portList, "PORTLIST", 0);
  const deny = compiled(PRODUCER.denyAll, "PORTLIST", 1);

  /* REGRESSION — consumePortOp swallowed the extra ports of `eq 443 8443`, so the residual guard
     found nothing left over and called the line evaluable, while the matcher modelled only the
     first port. A configuration permitting 443 AND 8443 was evaluated as permitting 443, giving a
     definite "denied" for tcp/8443 with no caveat. The one token that would have tripped the
     residual guard was eaten by the branch whose matcher cannot represent it. */
  it("refuses the line because the model carries one port per operator", () => {
    const ev = lineEvaluability(portList);
    expect(ev.evaluable).toBe(false);
    expect(ev.reason).toContain("8443");
    expect(ev.reason).toMatch(/one port per operator/);
  });

  it("does not deny the second port of a list that permits it", () => {
    const named = { PORTLIST: [portList, deny] };
    const acl = evaluateAcls("core1", flowOn("tcp", 8443), SRC, DST, named);
    expect(acl.verdict).toBe("indeterminate");
    expect(acl.decidedBy?.cite).toBe("acls.core1.PORTLIST[0]");
  });

  it("still denies a port a single-port line genuinely excludes", () => {
    // The control: the real PROTECT_SERVERS line permits only 443, and nothing about this guard
    // turns a readable port test into a blanket unknown.
    const single = fabric.acls["core1"]!["PROTECT_SERVERS"]![0]!;
    expect(lineEvaluability(single).evaluable).toBe(true);
    const acl = evaluateAcls("core1", flowOn("tcp", 8443), SRC, DST, { CONTROL: [single, deny] });
    expect(acl.verdict).toBe("deny");
    expect(acl.decision?.lineIndex).toBe(1);
  });
});

describe("an unresolvable object-group is this model's gap, not the collector's", () => {
  /* REGRESSION — the engine told the user, as cited evidence on every core1 trace, that MGMT_IN
     "references object-group MGMT_HOSTS, whose members were not collected". The engine reads
     fabric.json and cannot see the source snapshot, so it had no evidence for that claim; the
     members' absence is a property of tools/compile-snapshot.mjs, which emits no object-group
     table. Reporting a modelling gap as a collection gap is the same defect class the whole module
     exists to prevent, pointed at ourselves. */
  /* AMENDED 2026-09-21, and the amendment is the point of the original test.
     The premise line below — `expect(Object.keys(fabric)).not.toContain("object_groups")` — was
     written to make this test fail loudly if the compiler ever started carrying groups. It did
     exactly that. The compiler now emits `objectGroups`, so MGMT_HOSTS resolves and is no longer
     an example of an unresolvable reference. The DOCTRINE is untouched and still tested, on a
     group that genuinely is not carried: our modelling limits must never be described as the
     collector's gaps. */
  it("describes the absence as a limit of the compiled model and claims nothing about collection", () => {
    const line: AclLine = {
      index: 0,
      action: "permit",
      raw: "permit tcp object-group ABSENT_GROUP any eq 22",
      proto: "tcp",
      src: { ip: null, wild: null, group: "ABSENT_GROUP" },
      dst: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      sport: null,
      dport: { op: "eq", val: 22 },
      unevaluable: false,
      unmodeledQualifiers: [],
      established: false,
      icmpType: null,
      timeRange: null,
      cite: "acls.core1.SYNTHETIC[0]",
    };
    expect(resolveObjectGroup("core1", "ABSENT_GROUP"), "the premise, checked").toBeNull();
    const ev = lineEvaluability(line);
    expect(ev.evaluable).toBe(false);
    expect(ev.reason).toContain("ABSENT_GROUP");
    expect(ev.reason).toContain("this compiled evidence model does not carry");
    expect(ev.reason).not.toMatch(/were not collected/);
  });

  it("never says a CARRIED group's members were not collected", () => {
    // The original defect, now impossible for MGMT_HOSTS: the members are in the model.
    const group = fabric.objectGroups["core1"]?.["MGMT_HOSTS"];
    expect(group?.members.length).toBeGreaterThan(0);
    const reason = lineEvaluability(fabric.acls["core1"]!["MGMT_IN"]![0]!).reason ?? "";
    expect(reason).not.toMatch(/not collected/i);
    expect(reason).not.toMatch(/does not carry/i);
  });
});

describe("an FHRP group's hosts ingress at the member observed Active", () => {
  /* REGRESSION — ingress used to be ordered by host NAME and never read fhrpRole. For VLAN 20 the
     evidence records core2 Active and core1 Standby, yet the flow ingressed at core1 purely because
     "core1" sorts first.
     UPDATED 2026-09-22 (auditor, B2): the virtual address 10.0.20.1 itself is no longer walked at
     all — a packet sourced from it is originated by the group's active router and arrives inbound on
     no interface — so the ordering is pinned on a HOST in the subnet, and the VIP on its refusal. */
  const vip = traceFlow(tcp("10.0.20.1", "10.0.30.10", 443));
  const host = traceFlow(tcp("10.0.20.50", "10.0.30.10", 443));

  it("a host in the subnet enters at the observed Active member", () => {
    const active = fabric.l3.find((r) => r.vlan === 20 && r.fhrpRole === "Active")!;
    expect(active.host).toBe("core2"); // l3_forwarding[4]; the premise, read from the data
    expect(host.hops[0]!.host).toBe(active.host);
  });

  it("discloses the other group member rather than silently picking one", () => {
    const naming = host.caveats.filter((c) => c.includes("core1"));
    expect(naming.length).toBeGreaterThan(0);
    expect(naming.join(" ")).toMatch(/Standby|point-in-time|may enter via/);
  });

  it("the virtual address is refused as router-originated, naming every group member", () => {
    expect(refusalOf(vip)?.kind).toBe("router-originated");
    expect(vip.hops).toEqual([]);
    expect(refusalOf(vip)?.reason).toMatch(/core1/);
    expect(refusalOf(vip)?.reason).toMatch(/core2/);
  });

  it("does not manufacture ambiguity where one host owns an address twice", () => {
    // core1's Vlan10 address is also a `local` /32 in its RIB: two records, one host.
    const t = traceFlow(tcp("10.0.10.2", "10.0.30.10", 443));
    expect(refusalOf(t)?.kind).toBe("router-originated");
    expect(t.claim).not.toContain("core1, core1");
    expect(refusalOf(t)?.reason).not.toContain("core1, core1");
  });
});

describe("a subnet's own address is not a host, on the way in or the way out", () => {
  /* REGRESSION — hostAddressIn refuses to EMIT 10.0.30.0 or 10.0.30.255, and ip.test.ts asserts
     that. The same module then accepted both as flow endpoints and answered "delivered", so the
     knowledge existed on the generation path and was missing on the input path. */
  it("does not call a network or directed-broadcast destination delivered", () => {
    for (const dst of ["10.0.30.0", "10.0.30.255"]) {
      const t = traceFlow(tcp("10.0.10.50", dst, 443));
      expect(t.outcome, dst).toBe("indeterminate");
      expect(t.hops.filter((h) => h.verdict === "delivered"), dst).toEqual([]);
      expect(t.claim, dst).toMatch(/network address|directed-broadcast address/);
      expect(t.caveats.join(" "), dst).toContain("ip directed-broadcast");
      expect(t.hops[t.hops.length - 1]!.decidedBy!.kind).toBe("absence");
    }
    // Control: a host address in the same prefix is NOT given the non-host sentence (it is
    // indeterminate for a different, ACL reason — see "a permit that steps over an undecidable line").
    const control = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443));
    expect(control.claim).not.toMatch(/network address|directed-broadcast address/);
    // And a host address on a prefix with no undecided input is still delivered.
    expect(traceFlow(tcp("10.0.20.10", "10.0.10.10", 443)).outcome).toBe("delivered");
  });

  it("refuses to simulate a flow sourced from a subnet address", () => {
    for (const src of ["10.0.10.0", "10.0.10.255"]) {
      const t = traceFlow(tcp(src, "10.0.30.10", 443));
      expect(t.outcome, src).toBe("out-of-scope");
      expect(t.hops, src).toEqual([]);
      expect(t.claim, src).toContain(src);
      expect(t.claim, src).toMatch(/not a host address/);
    }
  });

  it("leaves a /31 alone, where both addresses really are hosts", () => {
    const p = parsePrefix("10.0.30.0/31")!;
    expect(addressRoleIn(p, parseIpv4("10.0.30.0")!)).toBe("host");
  });
});

/* ── A2: an egress the RIB already decides is not "not observed" ───────────────────────────────── */
describe("a next-hop-only route's egress is resolved through the same host's RIB", () => {
  it("0.0.0.0/0 via 10.0.10.254 leaves by Vlan10, citing both route records", () => {
    const t = traceFlow(tcp("10.0.10.50", "8.8.8.8", 443));
    const hop = t.hops[0]!;
    expect(hop.host).toBe("core1");
    expect(hop.nextHop).toBe("10.0.10.254");
    expect(hop.outIntf).toBe("Vlan10");
    const cites = hop.evidence.filter((e) => e.kind === "route").map((e) => e.cite);
    expect(cites).toContain("routes.core1[0]");
    expect(cites).toContain("routes.core1[2]");
  });

  it("stops after one level and refuses a non-connected resolution", () => {
    const winner = { prefix: "0.0.0.0/0", source: "static", nextHop: "192.0.2.1", outIntf: null, adminDistance: 1, cite: "routes.x[0]" };
    const recursive = { prefix: "192.0.2.0/24", source: "static", nextHop: "10.9.9.9", outIntf: null, adminDistance: 1, cite: "routes.x[1]" };
    expect(resolveEgress("x", winner, parseIpv4("8.8.8.8")!, [winner, recursive])).toBeNull();
  });
});
