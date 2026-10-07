/** A3: real engine walks over explicit synthetic collection records. No comparison, ACL evaluator,
 * binding reader or path-gap producer is mocked. Each case reloads the records and engine together,
 * so the actual evaluator owns the decision and the ordinary alternate/cache/finally path is used.
 * These fixtures prove the bounded refusal claim, not collection custody or A3 acceptance.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AclLine, Flow, Hop, L3Interface, RouteEntry, Trace } from "../core/types";
import { nameKeyed, own } from "../core/own";

type DatasetModule = typeof import("../core/dataset");
type BindingRecord = DatasetModule["aclBindings"]["hosts"][string][number];
type Mode = "same" | "different-line" | "different-host" | "different-interface" | "ambiguous" | "missing" | "implicit" | "delivery" | "received" | "shared-delivery" |
  "chosen-unmodeled" | "chosen-absence" | "chosen-rib-gap" | "wrong-direction" | "same-interface-ambiguous";
const FLOW: Flow = { srcIp: "10.80.10.50", dstIp: "10.80.30.50", protocol: "tcp", srcPort: null, dstPort: 22 };
const A = "ingress-a";
const B = "ingress-b";
const FILTER = "filter";
const NOT_RESTING = "does not rest on that choice";
const NOT_ESTABLISHED = "the same deciding refusal was not established across the ingresses";

function line(host: string, name: string, action: "permit" | "deny", index = 0): AclLine {
  return {
    index, action, raw: `${action} ip any any`, proto: "ip", src: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
    dst: { ip: "0.0.0.0", wild: "255.255.255.255", group: null }, sport: null, dport: null, unevaluable: false,
    unmodeledQualifiers: [], established: false, icmpType: null, timeRange: null, cite: `acls.${host}.${name}[${index}]`,
  };
}

async function records(mode: Mode): Promise<DatasetModule> {
  const original = await vi.importActual<DatasetModule>("../core/dataset");
  const f = structuredClone(original.fabricDocument);
  const binding = structuredClone(original.aclBindings);
  const rib = structuredClone(original.ribEvidence);
  const hosts = [A, B, FILTER];
  const svi = (host: string, vlan: number, address: string, role: string | null = null): L3Interface => ({
    host, vlan, sviIp: address, fhrp: role === null ? null : "HSRP", fhrpRole: role, vip: null,
    routingSource: null, nextHop: null, primarySubnet: null, secondary: null, tracking: null,
    trackingUnobserved: null, risk: null, riskUnobserved: null, severity: null, cite: `l3_interfaces.${host}.Vlan${vlan}`,
  });
  f.devices = hosts.map((host, order) => ({ ...f.devices[0]!, id: host, host, order }));
  f.links = []; f.findings = []; f.aclFindings = []; f.endpoints = []; f.protocols = []; f.crossLayer = []; f.physical = [];
  f.objectGroups = nameKeyed();
  f.l3 = [svi(A, 10, "10.80.10.1/24", "Active"), svi(B, 10, "10.80.10.2/24", "Standby"),
    svi(A, 11, "10.80.11.1/30"), svi(B, 12, "10.80.12.1/30"),
    svi(FILTER, 11, "10.80.11.2/30"), svi(FILTER, 12, "10.80.12.2/30"), svi(FILTER, 30, "10.80.30.1/24")];
  const route = (host: string, index: number, prefix: string, outIntf: string, nextHop: string | null = null): RouteEntry => ({
    prefix, outIntf, nextHop, source: nextHop === null ? "connected" : "static", adminDistance: nextHop === null ? 0 : 1, cite: `routes.${host}[${index}]`,
  });
  f.routes = nameKeyed([
    [A, [route(A, 0, "10.80.10.0/24", "Vlan10"), route(A, 1, "10.80.11.0/30", "Vlan11"), route(A, 2, "10.80.30.0/24", "Vlan11", "10.80.11.2")]],
    [B, [route(B, 0, "10.80.10.0/24", "Vlan10"), route(B, 1, "10.80.12.0/30", "Vlan12"), route(B, 2, "10.80.30.0/24", "Vlan12", "10.80.12.2")]],
    [FILTER, [route(FILTER, 0, "10.80.11.0/30", "Vlan11"), route(FILTER, 1, "10.80.12.0/30", "Vlan12"), route(FILTER, 2, "10.80.30.0/24", "Vlan30")]],
  ]);
  if (mode === "received") {
    // Both gateways feed one shared transit interface on the receiving device. Only the source
    // subnet has an ingress choice; the target is FILTER's own address, so this exercises the
    // receivedAtOwner denial branch rather than the ordinary forwarding denial branch.
    f.l3 = f.l3.filter((r) => !(r.host === B && r.vlan === 12));
    f.l3.push(svi(B, 11, "10.80.11.3/29"));
    for (const r of f.l3) if (r.vlan === 11) r.sviIp = r.sviIp!.replace("/30", "/29");
    f.routes = nameKeyed(Object.entries(f.routes).map(([host, rs]) => [host, rs.map((r) =>
      r.prefix === "10.80.11.0/30" || (host === B && r.prefix === "10.80.12.0/30")
        ? { ...r, prefix: "10.80.11.0/29", outIntf: "Vlan11" }
        : host === B && r.nextHop !== null ? { ...r, nextHop: "10.80.11.2", outIntf: "Vlan11" } : r,
    )]));
  }
  if (mode === "shared-delivery") {
    for (const host of [A, B]) {
      f.l3.push(svi(host, 30, host === A ? "10.80.30.2/24" : "10.80.30.3/24"));
      own(f.routes, host)![2] = route(host, 2, "10.80.30.0/24", "Vlan30");
    }
  }
  if (mode === "same-interface-ambiguous") {
    // A recorded hairpin route would send the packet back through its arrival interface.
    // The actual denial stops it first; both directions of Vlan11 are still traversed bindings.
    f.l3 = f.l3.filter((r) => !(r.host === FILTER && r.vlan === 30));
    own(f.routes, FILTER)![2] = route(FILTER, 2, "10.80.30.0/24", "Vlan11", "10.80.11.1");
  }
  const bound = (host: string, vlan: number, aclIn: string | null = null, aclOut: string | null = null): BindingRecord => ({
    port: `Vlan${vlan}`, vlan: String(vlan), switchportMode: null, aclIn, aclOut,
    gateCandidates: [], gateUnmodeled: [], runConfigObserved: true, cite: `interfaces.${host}.Vlan${vlan}`,
  });
  const filterBindings = [bound(FILTER, 11), bound(FILTER, 12), bound(FILTER, 30, null, "BLOCK")];
  if (mode === "different-interface") {
    filterBindings[0]!.aclIn = "BLOCK"; filterBindings[1]!.aclIn = "BLOCK"; filterBindings[2]!.aclOut = null;
  }
  if (mode === "ambiguous") filterBindings[1]!.aclIn = "BLOCK";
  if (mode === "same-interface-ambiguous") {
    filterBindings[0]!.aclIn = "BLOCK"; filterBindings[0]!.aclOut = "BLOCK"; filterBindings[2]!.aclOut = null;
  }
  if (mode === "different-line") filterBindings[1]!.aclIn = "OTHER";
  if (mode === "received") { filterBindings[0]!.aclIn = "BLOCK"; filterBindings[2]!.aclOut = null; }
  if (mode === "missing" || mode === "wrong-direction") {
    filterBindings[0]!.runConfigObserved = false; filterBindings[1]!.runConfigObserved = false; filterBindings[2]!.aclOut = null;
    if (mode === "wrong-direction") {
      // The records really bind the list OUTBOUND on the arrival interfaces. This does not
      // establish an inbound binding. Preserve the separate specificity-selection limitation.
      filterBindings[0]!.aclOut = "BLOCK"; filterBindings[1]!.aclOut = "BLOCK";
    }
  }
  binding.hosts = nameKeyed([
    [A, [bound(A, 10, mode === "chosen-unmodeled" ? "PASS" : null), bound(A, 11), ...(mode === "shared-delivery" ? [bound(A, 30)] : [])]],
    [B, [bound(B, 10, mode === "different-host" ? "BLOCK" : null), bound(B, mode === "received" ? 11 : 12), ...(mode === "shared-delivery" ? [bound(B, 30)] : [])]],
    [FILTER, filterBindings],
  ]);
  if (mode === "chosen-absence") own(binding.hosts, A)![0]!.runConfigObserved = false;
  f.interfaces = nameKeyed(hosts.map((host) => [host, own(binding.hosts, host)!.map((r) => ({
    port: r.port, status: "up", duplex: null, speed: null, portType: null, linkType: null,
    description: null, portChannel: null, pcProtocol: null, runConfigObserved: r.runConfigObserved, cite: r.cite,
  }))]));
  const deny = line(FILTER, "BLOCK", mode === "delivery" ? "permit" : "deny");
  // A specificity fallback must have an address-specific list to select. This fixture makes it
  // match the actual packet while the binding remains absent; it does not invent observed scope.
  if (mode === "missing" || mode === "wrong-direction") {
    deny.src = { ip: FLOW.srcIp, wild: "0.0.0.0", group: null };
    deny.raw = `deny ip host ${FLOW.srcIp} any`;
  }
  f.acls = nameKeyed([
    [A, nameKeyed([["PASS", [line(A, "PASS", "permit")]]])],
    [B, nameKeyed([["PASS", [line(B, "PASS", "permit")]], ["BLOCK", [line(B, "BLOCK", "deny")]]])],
    [FILTER, nameKeyed([["BLOCK", mode === "implicit" ? [] : [deny]], ["OTHER", [line(FILTER, "OTHER", "deny")]]])],
  ]);
  if (mode === "chosen-unmodeled") {
    const early = own(own(f.acls, A), "PASS")![0]!;
    early.raw = "permit tcp any any established"; early.proto = "tcp";
    early.established = true; early.unevaluable = true; early.unmodeledQualifiers = ["established"];
  }
  f.coverage = { ...f.coverage, routableHosts: hosts, aclHosts: hosts, unreadableRouteEntries: nameKeyed(), hostsWithRoutes: 3, hostsWithAcls: 3 };
  rib.hosts = nameKeyed(hosts.map((host) => [host, {
    protocols: rib.meta.routingProtocols.map((protocol) => ({ protocol, state: "not_running", reason: "synthetic fixture: no dynamic process", cite: `protocol_assessability.${host}.${protocol}` })),
    adjacencies: [], overlay: [],
  }]));
  if (mode === "chosen-rib-gap") own(rib.hosts, A)!.protocols[0]!.state = "not_collected";
  return { ...original, fabricDocument: f, aclBindings: binding, ribEvidence: rib };
}

async function load(mode: Mode) {
  vi.resetModules();
  vi.doMock("../core/dataset", () => records(mode));
  return import("./engine");
}

afterEach(() => {
  vi.doUnmock("../core/dataset");
  vi.resetModules();
});

const terminal = (t: Trace): Hop => {
  const h = t.hops.at(-1);
  expect(h, "the controlled flow reaches its terminal hop").toBeDefined();
  return h!;
};
const ingressCaveat = (t: Trace): string => t.caveats.find((c) => c.includes("was taken as ingress")) ?? "";

describe("A3 refusal identity through the real trace and alternate walk", () => {
  it("outcome-only witness: different deciding ACL lines cannot certify reproduction", async () => {
    const e = await load("different-line");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect([t.outcome, alternate.outcome]).toEqual(["denied", "denied"]);
    expect(terminal(t).decidedBy?.cite).toBe(`acls.${FILTER}.BLOCK[0]`);
    expect(terminal(alternate).decidedBy?.cite).toBe(`acls.${FILTER}.OTHER[0]`);
    const gap = e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate" && g.host === B);
    expect(gap?.label, "outcome-only witness").toContain(NOT_ESTABLISHED);
    expect(gap?.label).toContain(`acls.${FILTER}.BLOCK[0]`);
    expect(gap?.label).toContain(`acls.${FILTER}.OTHER[0]`);
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
    expect(t.claim).toContain("That denial is not decided");
  });

  it("binding witness: the same ACL line through different observed interfaces is not reproduced", async () => {
    const e = await load("different-interface");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect(terminal(t).decidedBy?.cite).toBe(`acls.${FILTER}.BLOCK[0]`);
    expect(terminal(alternate).decidedBy?.cite).toBe(`acls.${FILTER}.BLOCK[0]`);
    const bindings = (h: Hop) => h.evidence.filter((x) => x.raw === "acl_in: BLOCK").map((x) => x.cite);
    expect(bindings(terminal(t))).toEqual([`interfaces.${FILTER}.Vlan11`]);
    expect(bindings(terminal(alternate))).toEqual([`interfaces.${FILTER}.Vlan12`]);
    const gap = e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate");
    expect(gap, "binding witness").toBeDefined();
    expect(gap?.label).toContain(`interfaces.${FILTER}.Vlan11`);
    expect(gap?.label).toContain(`interfaces.${FILTER}.Vlan12`);
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("positive witness: identical uniquely observed refusals still reproduce", async () => {
    const e = await load("same");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect([terminal(t).host, terminal(alternate).host]).toEqual([FILTER, FILTER]);
    expect([terminal(t).decidedBy?.cite, terminal(alternate).decidedBy?.cite]).toEqual([`acls.${FILTER}.BLOCK[0]`, `acls.${FILTER}.BLOCK[0]`]);
    expect(e.unobservedPolicyInputs(t), "positive witness").toEqual([]);
    expect(ingressCaveat(t)).toContain(NOT_RESTING);
  });

  it("a denial at another host is not the same refusal", async () => {
    const e = await load("different-host");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect([terminal(t).host, terminal(alternate).host]).toEqual([FILTER, B]);
    expect(e.unobservedPolicyInputs(t).some((g) => g.kind === "ingress-alternate")).toBe(true);
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("multiple traversed bindings do not silently credit the first binding", async () => {
    const e = await load("ambiguous");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect(terminal(alternate).evidence.filter((x) => x.raw === "acl_in: BLOCK" || x.raw === "acl_out: BLOCK")).toHaveLength(2);
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain("without a unique observed path binding");
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain(NOT_ESTABLISHED);
    expect(t.claim).not.toContain("deciding refusal depends on the ingress");
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("a missing binding never becomes observed provenance", async () => {
    const e = await load("missing");
    const t = e.traceFlow(FLOW);
    expect(t.outcome).toBe("denied");
    expect(e.unobservedPolicyInputs(t).some((g) => g.kind === "acl-unbound-denial")).toBe(true);
    expect(e.unobservedPolicyInputs(t).some((g) => g.kind === "ingress-alternate")).toBe(true);
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain(NOT_ESTABLISHED);
    expect(t.claim).not.toContain("deciding refusal depends on the ingress");
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("implicit denial keeps the existing absence qualification", async () => {
    const e = await load("implicit");
    const t = e.traceFlow(FLOW);
    expect(t.outcome).toBe("denied");
    expect(terminal(t).decidedBy?.kind).toBe("absence");
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain("evidence recorded as absent");
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("a complete delivery retains its positive qualification", async () => {
    const e = await load("delivery");
    const t = e.traceFlow(FLOW);
    expect(t.outcome).toBe("delivered");
    expect(e.unobservedPolicyInputs(t)).toEqual([]);
    expect(e.isDefiniteDelivery(t)).toBe(true);
    expect(ingressCaveat(t)).toContain(NOT_RESTING);
  });

  it("a shared-subnet delivery at different routers is not turned into a refusal gap", async () => {
    const e = await load("shared-delivery");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect([terminal(t).host, terminal(alternate).host]).toEqual([A, B]);
    expect([t.outcome, alternate.outcome]).toEqual(["delivered", "delivered"]);
    expect(e.unobservedPolicyInputs(t)).toEqual([]);
    expect(e.isDefiniteDelivery(t)).toBe(true);
  });

  it("an identical received-at-device denial retains its actual evaluator decision", async () => {
    const e = await load("received");
    const f = { ...FLOW, dstIp: "10.80.30.1" };
    const t = e.traceFlow(f); const alternate = e.traceViaIngress(f, B);
    expect([t.outcome, alternate.outcome]).toEqual(["denied", "denied"]);
    expect([terminal(t).outIntf, terminal(alternate).outIntf]).toEqual([null, null]);
    expect(terminal(t).decidedBy?.cite).toBe(`acls.${FILTER}.BLOCK[0]`);
    expect(terminal(alternate).decidedBy?.cite).toBe(`acls.${FILTER}.BLOCK[0]`);
    expect(e.unobservedPolicyInputs(t)).toEqual([]);
    expect(ingressCaveat(t)).toContain(NOT_RESTING);
  });

  it("chosen-path witness: an earlier unmodeled hop cannot be hidden by an identical terminal denial", async () => {
    const e = await load("chosen-unmodeled");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect(t.hops[0]?.verdict).toBe("unmodeled");
    expect(e.blockingHop(t)?.hop.host).toBe(A);
    expect([t.outcome, alternate.outcome]).toEqual(["denied", "denied"]);
    expect([terminal(t).decidedBy?.cite, terminal(alternate).decidedBy?.cite]).toEqual([`acls.${FILTER}.BLOCK[0]`, `acls.${FILTER}.BLOCK[0]`]);
    const gap = e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate");
    expect(gap?.label, "chosen-path witness").toContain("chosen trace via ingress-a has unobserved or unmodelled inputs");
    expect(gap?.label).toContain(`acls.${A}.PASS[0]`);
    // The actual terminal ACL identities DO agree; the chosen path's earlier open input is
    // the reason, not a reconstruction of the identity from the first generic blocking hop.
    expect(gap?.label).not.toContain(NOT_ESTABLISHED);
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("a chosen-side absence does not become a complete alternate-ingress claim", async () => {
    const e = await load("chosen-absence");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect(t.hops[0]?.evidence.some((x) => x.kind === "absence" && x.cite === `interfaces.${A}.Vlan10`)).toBe(true);
    expect([terminal(t).decidedBy?.cite, terminal(alternate).decidedBy?.cite]).toEqual([`acls.${FILTER}.BLOCK[0]`, `acls.${FILTER}.BLOCK[0]`]);
    const gap = e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate");
    expect(gap?.label).toContain(`interfaces.${A}.Vlan10`);
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("a chosen-side incomplete route basis remains an explicit qualification", async () => {
    const e = await load("chosen-rib-gap");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect([terminal(t).decidedBy?.cite, terminal(alternate).decidedBy?.cite]).toEqual([`acls.${FILTER}.BLOCK[0]`, `acls.${FILTER}.BLOCK[0]`]);
    const ownGap = e.unobservedPolicyInputs(t).find((g) => g.kind === "rib-partial" && g.host === A);
    expect(ownGap).toBeDefined();
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain(ownGap!.cite);
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("direction applicability: an outbound-only arrival-interface record does not establish inbound provenance", async () => {
    const e = await load("wrong-direction");
    const { bindingAt } = await import("./bindings");
    expect(bindingAt(FILTER, "Vlan11", "out").kind).toBe("bound");
    expect(bindingAt(FILTER, "Vlan11", "in").kind).toBe("unknown");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    expect([t.outcome, alternate.outcome]).toEqual(["denied", "denied"]);
    expect([terminal(t).decidedBy?.cite, terminal(alternate).decidedBy?.cite]).toEqual([`acls.${FILTER}.BLOCK[0]`, `acls.${FILTER}.BLOCK[0]`]);
    expect(terminal(t).evidence.some((x) => x.raw === "acl_out: BLOCK")).toBe(false);
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain("without a unique observed path binding");
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("direction ambiguity: the same traversed interface bound in both directions is not one provenance", async () => {
    const e = await load("same-interface-ambiguous");
    const t = e.traceFlow(FLOW); const alternate = e.traceViaIngress(FLOW, B);
    const records = terminal(t).evidence.filter((x) => x.raw === "acl_in: BLOCK" || x.raw === "acl_out: BLOCK");
    expect(records.map((x) => [x.cite, x.raw])).toEqual([
      [`interfaces.${FILTER}.Vlan11`, "acl_in: BLOCK"], [`interfaces.${FILTER}.Vlan11`, "acl_out: BLOCK"],
    ]);
    expect([terminal(t).decidedBy?.cite, terminal(alternate).decidedBy?.cite]).toEqual([`acls.${FILTER}.BLOCK[0]`, `acls.${FILTER}.BLOCK[0]`]);
    expect(e.unobservedPolicyInputs(t).find((g) => g.kind === "ingress-alternate")?.label).toContain("without a unique observed path binding");
    expect(ingressCaveat(t)).not.toContain(NOT_RESTING);
  });

  it("alternate queries restore ingress ordering and repeat with a stable case census", async () => {
    const e = await load("different-interface");
    const reverseFirst = e.traceViaIngress(FLOW, B);
    const t = e.traceFlow(FLOW);
    expect(t.hops[0]?.host).toBe(A);
    expect(reverseFirst.hops[0]?.host).toBe(B);
    expect(e.traceViaIngress(FLOW, B)).toBe(reverseFirst);
    const repeated = e.traceFlow(FLOW);
    expect(repeated.hops[0]?.host).toBe(A);
    expect(e.unobservedPolicyInputs(repeated)).toEqual(e.unobservedPolicyInputs(t));
    expect(repeated.caveats).toEqual(t.caveats);
  });
});
