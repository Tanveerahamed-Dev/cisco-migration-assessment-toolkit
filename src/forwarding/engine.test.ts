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
import { claimBadge, scopeTuple, T1_verdict } from "../core/claims";
import type { AclLine, Flow } from "../core/types";
import { addressRoleIn, formatIpv4, parseInterfaceAddress, parseIpv4, parsePrefix, prefixContains } from "./ip";
import {
  blockingHop,
  chooseRoute,
  counterexample,
  evaluateAcls,
  lineEvaluability,
  matchTri,
  resolveNextHost,
  resolveObjectGroup,
  suggestedFlows,
  TTL_LIMIT,
  traceFlow,
} from "./engine";

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

describe("delivered", () => {
  // 10.0.10.50 is a real endpoint address; 10.0.30.0/24 is the destination space PROTECT_SERVERS
  // names, and 443 is the port its first line permits.
  const trace = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443));

  it("is delivered on core1's connected route, citing the exact winning route", () => {
    expect(trace.outcome).toBe("delivered");
    const last = trace.hops[trace.hops.length - 1]!;
    expect(last.host).toBe("core1");
    expect(last.verdict).toBe("delivered");
    expect(last.decidedBy?.kind).toBe("route");
    expect(last.decidedBy?.cite).toBe("routes.core1[6]"); // 10.0.30.0/24 connected via Vlan30
    expect(last.outIntf).toBe("Vlan30");
  });

  it("shows the routes it beat, so 'why not that one' is answerable", () => {
    const last = trace.hops[trace.hops.length - 1]!;
    expect(last.alternatives.map((a) => a.prefix)).toEqual(["10.0.0.0/16", "0.0.0.0/0"]);
  });

  it("records the permitting ACL line as evidence even though it did not block", () => {
    const acl = trace.hops[0]!.evidence.find((e) => e.cite === "acls.core1.PROTECT_SERVERS[0]");
    expect(acl?.raw).toBe("permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443");
  });

  it("still qualifies the claim: delivery is proven only over what was collected", () => {
    expect(trace.caveats.length).toBeGreaterThan(0);
    expect(trace.caveats.join(" ")).toMatch(/access-group|binding/i);
    expect(trace.claim).toMatch(/delivered/);
    expect(trace.claim).toMatch(/core1/);
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
    expect(blocked!.evidence.label).toContain("line 3");
    expect(blocked!.evidence.label).toContain("core1");
  });

  it("is not poisoned by the unevaluable icmp line above it, because protocol excludes it", () => {
    // acls.core1.PROTECT_SERVERS[2] is `permit icmp any 10.0.30.0 0.0.0.255 echo-reply` — the
    // snapshot marks it INDETERMINATE, but an icmp ACE cannot match a tcp packet.
    expect(trace.claim).toMatch(/denied/);
    expect(trace.caveats.join(" ")).toContain("PROTECT_SERVERS");
  });

  it("offers a counterexample: the same pair on a port the ACL does permit", () => {
    const cx = counterexample(flow, trace);
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(cx.flow.srcIp).toBe(flow.srcIp);
    expect(cx.flow.dstIp).toBe(flow.dstIp);
    expect([443, 22]).toContain(cx.flow.dstPort);
    expect(cx.trace.outcome).toBe("delivered");
  });

  it("cites the line its own trace was decided by, not the line that generated the candidate", () => {
    /* Candidates are varied by protocol and port ONLY — never by address — and the verdict comes
       from an independent traceFlow() run. So the line that SUGGESTED a candidate routinely cannot
       match the flow's addresses at all, and narrating it produces a confident sentence about
       evidence nobody checked.
       Measured on the shipped snapshot, the card asserted: "tcp/22 from 10.0.10.50 to 10.0.30.10 is
       delivered: core1 ACL MGMT_IN line 0 (acls.core1.MGMT_IN[0]) permits tcp/22 for this address
       pair" — while acls.core1.MGMT_IN[0] is `permit tcp object-group MGMT_HOSTS any eq 22` whose
       group resolves to 10.0.99.10/32 and 10.0.40.0/24, excluding 10.0.10.50 entirely, and while
       the engine's own trace of that very flow named acls.core1.PROTECT_SERVERS[1].
       This asserts the invariant that makes the sentence checkable: every ACL citation in the
       rationale must appear in the evidence of a fresh trace of the counterexample's own flow. */
    const cx = counterexample(flow, trace);
    expect(cx.found).toBe(true);
    if (!cx.found) return;

    const fresh = traceFlow(cx.flow);
    expect(fresh.outcome).toBe("delivered");
    const evidenceCites = new Set<string>();
    for (const hop of fresh.hops) {
      if (hop.decidedBy !== null) evidenceCites.add(hop.decidedBy.cite);
      for (const e of hop.evidence) evidenceCites.add(e.cite);
    }

    const citedInRationale = cx.rationale.match(/acls\.[A-Za-z0-9_.-]+\[\d+\]/g) ?? [];
    // A rationale with no citation at all is allowed (it then makes no causal claim); a rationale
    // that DOES cite must cite something the trace actually consulted.
    for (const cite of citedInRationale) expect([...evidenceCites]).toContain(cite);

    // And on this snapshot the flow really is decided by a line, so the honest sentence names one.
    expect(citedInRationale.length).toBeGreaterThan(0);
  });
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
    for (const f of probes) {
      const t = traceFlow(f);
      if (t.unmodelledHosts.length > 0) expect(t.outcome).toBe("indeterminate");
    }
  });
});

describe("ACLs that were NOT applied are reported as unknown, not as absent", () => {
  it("names MGMT_IN, whose object-group could never be scored, on a core1 trace", () => {
    const t = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443));
    const joined = t.caveats.join(" ");
    expect(joined).toContain("MGMT_IN");
    expect(joined).toMatch(/not evidence/i);
  });
});

/* ── the three claim-honesty defects found by an external audit, 2026-09-21 ───────────────────
   Each of these was a positive claim the code asserted rather than measured. They are pinned
   here against the REAL compiled snapshot, not a fixture, because each one was true-looking and
   wrong on the app's own headline flow. */
describe("undecidability is a property of the deciding HOST, not of the ACL the heuristic picked", () => {
  const headline = tcp("10.0.10.50", "10.0.30.10", 443);

  it("the preconditions this test rests on are the real ones", () => {
    // If these change, the assertions below stop meaning what they say.
    const inet = fabric.acls["core1"]?.["INET_RETURN"] ?? [];
    expect(lineEvaluability(inet[0]!).evaluable).toBe(false);
    expect(lineEvaluability(inet[1]!).evaluable).toBe(false);
    expect(matchTri(inet[0]!, headline, parseIpv4("10.0.10.50")!, parseIpv4("10.0.30.10")!)).toBe("yes");
    expect(matchTri(inet[1]!, headline, parseIpv4("10.0.10.50")!, parseIpv4("10.0.30.10")!)).toBe("yes");
    // and no access-group binding exists anywhere, so "not applied" is a heuristic, not evidence
    expect(JSON.stringify(fabric).includes("access-group")).toBe(false);
  });

  it("a line in a NON-selected ACL that could match and cannot be decided lowers the badge", () => {
    const t = traceFlow(headline);
    const cites = t.hops.flatMap((h) => h.evidence).map((e) => String(e.cite));
    expect(cites).toContain("acls.core1.INET_RETURN[0]");
    expect(cites).toContain("acls.core1.INET_RETURN[1]");
    expect(scopeTuple(t).indeterminateEvidence).toBeGreaterThan(0);
    expect(claimBadge(t)).not.toBe("SCOPED");
    expect(T1_verdict(t)).not.toContain("0 evidence items were indeterminate");
  });

  it("the verdict is still decided by the line that decided it, not by the undecidable ones", () => {
    const t = traceFlow(headline);
    expect(t.outcome).toBe("delivered");
    const aclHop = t.hops.find((h) => h.evidence.some((e) => e.kind === "acl"));
    expect(String(aclHop?.evidence.find((e) => e.kind === "acl")?.cite)).toBe("acls.core1.PROTECT_SERVERS[0]");
  });
});

describe("the not-applied caveat MEASURES its claim about each discarded list", () => {
  it("names the specific undecidable line instead of calling it a catch-all", () => {
    const joined = traceFlow(tcp("10.0.10.50", "10.0.30.10", 443)).caveats.join(" ");
    expect(joined).toContain("acls.core1.INET_RETURN[1]");
    expect(joined).toMatch(/INET_RETURN \(matches this flow at acls\.core1\.INET_RETURN\[1\]/);
  });

  it("says 'only through catch-all lines' ONLY where every matching line really is any/any", () => {
    // VOICE_FILTER's only line reachable by this flow is `deny ip any any`; MGMT_IN's is the same.
    // The phrase is allowed there and nowhere else, so every emission of it is re-derived.
    for (const flow of [tcp("10.0.10.50", "10.0.30.10", 443), tcp("10.0.10.50", "10.0.30.10", 22), tcp("10.0.10.50", "10.0.30.10", 3389)]) {
      const caveats = traceFlow(flow).caveats.join(" ");
      for (const m of caveats.matchAll(/(\w+) \(matches this flow only through catch-all lines\)/g)) {
        const name = m[1]!;
        const lines = fabric.acls["core1"]?.[name] ?? [];
        const src = parseIpv4(flow.srcIp)!;
        const dst = parseIpv4(flow.dstIp)!;
        const matching = lines.filter((l) => matchTri(l, flow, src, dst) !== "no");
        expect(matching.length).toBeGreaterThan(0);
        for (const l of matching) expect(l.raw).toMatch(/\bany\s+any\b/);
      }
    }
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
    const delivered = [22, 443]
      .flatMap((p) => ["10.0.30.10", "10.0.30.50", "10.0.30.100"].map((d) => tcp("10.0.10.50", d, p)))
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
   * A wall-clock TRIPWIRE, not a latency budget — and the distinction is why this reads the way it
   * does.
   *
   * A unit test does not control the machine. This suite routinely runs while a dozen other
   * processes compete for the CPU, and the original form of this test (a single measurement against
   * a 5 ms bound) failed under that load and passed on a quiet run. A red that means "the host was
   * busy" is indistinguishable from a red that means "someone made this quadratic", which makes the
   * gate worse than useless: it trains people to re-run until green.
   *
   * So: take a MEDIAN over repeats, which is robust to a scheduler stall, and set the bound far
   * above any plausible one. What survives is the thing a unit test can honestly assert — that the
   * algorithm has not blown up. The actual 200 ms interaction budget is measured against the real
   * application by `review/measure-inp.mjs`, which labels itself LABORATORY and reports NOT
   * MEASURED rather than guessing.
   */
  it("does not blow up algorithmically on any suggested flow", () => {
    const TRIPWIRE_MS = 50; // 10x the 5 ms design target; see the note above
    for (const f of suggestedFlows()) {
      const runs: number[] = [];
      for (let i = 0; i < 7; i++) runs.push(traceFlow(f.flow).elapsedMs);
      runs.sort((a, b) => a - b);
      const median = runs[3]!;
      expect(
        median,
        `${f.id} median ${median.toFixed(2)} ms over 7 runs (slowest ${runs[6]!.toFixed(2)} ms)`,
      ).toBeLessThan(TRIPWIRE_MS);
    }
  });

  it("keeps the counterexample search inside the same interaction budget", () => {
    /* The UI asks for a counterexample in the same gesture that runs the trace, so its cost is part
       of that interaction, not a separate one.

       A TRIPWIRE, measured the same way as the one above and for the same reason. This test used
       to take a SINGLE measurement against a 5 ms bound — sixteen lines below the comment
       explaining why that form is invalid here — and it duly went red under parallel load during
       an audit, saying nothing whatever about `counterexample`. Median over repeats, bound set far
       above any plausible quiet-run figure. */
    const TRIPWIRE_MS = 50; // 10x the 5 ms design target; see the note above
    const t = traceFlow(flow);
    const runs: number[] = [];
    for (let i = 0; i < 7; i++) {
      const before = performance.now();
      counterexample(flow, t);
      runs.push(performance.now() - before);
    }
    runs.sort((a, b) => a - b);
    const median = runs[3]!;
    expect(
      median,
      `counterexample median ${median.toFixed(2)} ms over 7 runs (slowest ${runs[6]!.toFixed(2)} ms)`,
    ).toBeLessThan(TRIPWIRE_MS);
    expect(counterexample(flow, t).found).toBe(true);
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

describe("an FHRP virtual address ingresses at the member observed Active", () => {
  /* REGRESSION — step 1 of resolveIngress sorted owners by hasRib then host NAME and never read
     fhrpRole, and emitted no caveat when several hosts owned the address. For VLAN 20 the evidence
     records core2 Active and core1 Standby, yet 10.0.20.1 — the address every VLAN-20 host uses as
     its gateway — ingressed at core1 purely because "core1" sorts first. Since only core1 holds a
     route to 10.0.30.0/24, the same forwarding question then returned two contradictory DEFINITE
     verdicts depending only on which address in one subnet you typed. */
  const vip = traceFlow(tcp("10.0.20.1", "10.0.30.10", 443));
  const host = traceFlow(tcp("10.0.20.50", "10.0.30.10", 443));

  it("enters at the observed Active member, citing the record that observed the role", () => {
    const active = fabric.l3.find((r) => r.vlan === 20 && r.fhrpRole === "Active")!;
    expect(active.host).toBe("core2"); // l3_forwarding[4]; the premise, read from the data
    expect(vip.hops[0]!.host).toBe(active.host);
  });

  it("gives the gateway address and a host in its subnet the same answer", () => {
    expect(vip.hops[0]!.host).toBe(host.hops[0]!.host);
    expect(vip.outcome).toBe(host.outcome);
  });

  it("discloses the other group member rather than silently picking one", () => {
    const naming = vip.caveats.filter((c) => c.includes("core1") && c.includes("10.0.20.1"));
    expect(naming.length).toBeGreaterThan(0);
    expect(naming.join(" ")).toMatch(/Standby|point-in-time/);
  });

  it("does not manufacture ambiguity where one host owns an address twice", () => {
    // core1's Vlan10 address is also a `local` /32 in its RIB: two records, one host.
    const t = traceFlow(tcp("10.0.10.2", "10.0.30.10", 443));
    expect(t.hops[0]!.host).toBe("core1");
    expect(t.caveats.filter((c) => c.includes("is an address of") && c.includes("core1, core1"))).toEqual([]);
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
    // Control: a host address in the same prefix, same port, is still delivered.
    expect(traceFlow(tcp("10.0.10.50", "10.0.30.10", 443)).outcome).toBe("delivered");
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
