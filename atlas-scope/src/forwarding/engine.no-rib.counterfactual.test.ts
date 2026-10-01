/**
 * engine.no-rib.counterfactual.test.ts — a host whose routing table was NOT collected, run on the real
 * compiled fabric with ONE counterfactual: that host's collected RIB (and ACLs) withdrawn.
 *
 * Why a counterfactual. On the regenerated reference sample every SVI gateway holds a collected RIB
 * (core1, core2, dist1, dist2), and every next hop a route names is an address of one of them, so NO trace
 * reaches a host without a RIB: the "unmodeled — no routing table" hop, the claim that says so, the
 * `acl-uncollected` gap at the hop that stops the trace, and the "unmodelled" preset have no real trace to
 * run on. They are the engine's honesty about absence, so they still have to execute. The subject is
 * resolved by PROPERTY — the observed-Active SVI gateway holding a collected RIB with the fewest collected
 * ACL lines (ties by name) — and its routes and ACLs are withdrawn, with the coverage lists kept consistent;
 * every other record is the real compiled evidence. Vitest isolates modules per file.
 *
 * Moved here from engine.test.ts, whose subject (dist1, "10.0.40.0/24 is dist1's Vlan40 SVI subnet; no RIB
 * was collected for dist1") gained a collected table in the regenerated sample:
 *   - "unmodelled forwarding is never delivery" (both tests),
 *   - the unmodeled half of "records the ACL gap at a hop that STOPS the trace too",
 *   - "never lets an uncollected RIB or unevaluable line read as a clean path" (its non-vacuity pin).
 */
import { describe, expect, it, vi } from "vitest";

interface FabricShape {
  routes: Record<string, unknown[]>;
  acls: Record<string, Record<string, unknown[]>>;
  l3: { host: string | null; sviIp: string | null; fhrpRole: string | null }[];
  coverage: { routableHosts: string[]; aclHosts: string[]; hostsWithRoutes: number; hostsWithAcls: number };
}

const cf = vi.hoisted(() => ({ host: null as string | null }));

vi.mock("../data/fabric.json", async () => {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const lines = (h: string): number => Object.values(c.acls[h] ?? {}).reduce((n, ls) => n + ls.length, 0);
  const hosts = [...new Set(c.l3.filter((r) => r.host !== null && (r.fhrpRole ?? "").toLowerCase() === "active" && c.routes[r.host] !== undefined).map((r) => r.host!))];
  hosts.sort((a, b) => lines(a) - lines(b) || a.localeCompare(b));
  const x = hosts[0];
  if (x === undefined) throw new Error("precondition: some observed-Active SVI gateway holds a collected RIB");
  cf.host = x;
  delete c.routes[x];
  delete c.acls[x];
  c.coverage.routableHosts = c.coverage.routableHosts.filter((h) => h !== x);
  c.coverage.aclHosts = c.coverage.aclHosts.filter((h) => h !== x);
  c.coverage.hostsWithRoutes = c.coverage.routableHosts.length;
  c.coverage.hostsWithAcls = c.coverage.aclHosts.length;
  return { default: c };
});

import { claimBadge, T1_verdict } from "../core/claims";
import { fabric, hasRib } from "../core/data";
import type { Flow } from "../core/types";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "./ip";
import { suggestedFlows, traceFlow, unobservedPolicyInputs } from "./engine";

const x = (): string => {
  expect(cf.host, "precondition: the fixture chose a host").not.toBeNull();
  return cf.host!;
};

/** A host address in a subnet X is the observed-Active gateway of, toward an address in another observed subnet. */
function flowFromX(): Flow {
  const own = fabric.l3.find((r) => r.host === x() && (r.fhrpRole ?? "").toLowerCase() === "active" && r.sviIp !== null)!;
  const p = parseInterfaceAddress(own.sviIp!)!.prefix;
  const other = fabric.l3.find((r) => r.host !== x() && r.sviIp !== null && parseInterfaceAddress(r.sviIp) !== null && formatIpv4(parseInterfaceAddress(r.sviIp)!.prefix.base) !== formatIpv4(p.base))!;
  return {
    srcIp: formatIpv4(hostAddressIn(p, 50)!),
    dstIp: formatIpv4(hostAddressIn(parseInterfaceAddress(other.sviIp!)!.prefix, 10)!),
    protocol: "tcp",
    dstPort: 443,
    srcPort: null,
  };
}

describe("the fixture", () => {
  it("withdraws exactly one host's RIB and ACLs, and the coverage says so", () => {
    expect(hasRib(x())).toBe(false);
    expect(fabric.coverage.routableHosts).not.toContain(x());
    expect(fabric.coverage.aclHosts).not.toContain(x());
    expect(fabric.coverage.routableHosts.length, "other RIB hosts remain").toBeGreaterThan(0);
  });
});

describe("unmodelled forwarding is never delivery (moved from engine.test.ts)", () => {
  it("stops at the host whose forwarding table we do not hold", () => {
    const trace = traceFlow(flowFromX());
    expect(trace.outcome).toBe("indeterminate");
    expect(trace.outcome).not.toBe("delivered");
    expect(trace.unmodelledHosts).toContain(x());
    const hop = trace.hops.find((h) => h.host === x())!;
    expect(hop.verdict).toBe("unmodeled");
    expect(hop.decidedBy?.kind).toBe("absence");
    expect(hop.decidedBy?.raw).toBeNull();
  });

  it("says so in the claim rather than implying a clean path", () => {
    const trace = traceFlow(flowFromX());
    expect(trace.claim).toContain(x());
    expect(trace.claim.toLowerCase()).toMatch(/cannot|not collected|no .*routing tab/);
  });

  it("records the ACL gap at the unmodeled hop that STOPS the trace (critic B1, 2026-09-21)", () => {
    const trace = traceFlow(flowFromX());
    expect(trace.hops.some((h) => h.host === x() && h.verdict === "unmodeled")).toBe(true);
    expect(unobservedPolicyInputs(trace).map((g) => [g.host, g.kind])).toContainEqual([x(), "acl-uncollected"]);
    expect(T1_verdict(trace)).toMatch(new RegExp(`no ACLs collected for ${x()}`));
    expect(claimBadge(trace)).toBe("INDETERMINATE");
  });

  it("never lets an uncollected RIB read as a clean path — over every suggested flow and a sweep from the host's subnets", () => {
    const probes: Flow[] = [...suggestedFlows().map((s) => s.flow), flowFromX()];
    for (const r of fabric.l3) {
      const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
      const d = a === null ? null : hostAddressIn(a.prefix, 10);
      if (d !== null) probes.push({ ...flowFromX(), dstIp: formatIpv4(d) });
    }
    let exercised = 0;
    for (const f of probes) {
      const t = traceFlow(f);
      if (t.unmodelledHosts.length > 0) exercised += 1;
      expect(
        t.unmodelledHosts.length === 0 || t.outcome === "indeterminate",
        `${JSON.stringify(f)}: unmodelled ${t.unmodelledHosts.join(", ")} but outcome ${t.outcome}`,
      ).toBe(true);
    }
    expect(exercised, "probes whose trace crosses an unmodelled host (the case this test is about)").toBeGreaterThan(0);
  });
});

describe("the 'unmodelled' preset", () => {
  it("is offered, and its trace stops at the gateway its rationale names as holding no table", () => {
    const s = suggestedFlows().find((f) => f.id === "unmodelled");
    expect(s, "a gateway with no collected RIB yields the preset").toBeDefined();
    const t = traceFlow(s!.flow);
    expect(s!.expectedOutcome).toBe("indeterminate");
    expect(t.hops[0]!.host).toBe(x());
    expect(t.hops[0]!.verdict).toBe("unmodeled");
    expect(s!.rationale.startsWith(`${x()} gateways `)).toBe(true);
    expect(s!.rationale).toContain("no routing table was collected");
    expect(s!.srcProvenance.kind).toBe("derived-from-observed-subnet");
  });
});
