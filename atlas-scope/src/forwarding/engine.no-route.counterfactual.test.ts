/**
 * engine.no-route.counterfactual.test.ts — "no route" at a gateway, and the preset that poses it, run on
 * the real compiled fabric with ONE counterfactual: a gateway's default route removed.
 *
 * Why a counterfactual. The regenerated reference sample gives every collected table a default route
 * (core1 static, core2/dist1/dist2 OSPF external), so no trace on it ends in a first-hop "no-route" and
 * the engine rightly offers no "no-route" preset. The branch still has to execute somewhere: the drop
 * cites the table it searched, a host with no collected ACLs stays an unobserved filter at the hop that
 * stops the trace, and the preset's rationale is built from THAT hop's own decidedBy
 * (disc-app-sample-assumptions #2). The subject is resolved by PROPERTY — the first observed-Active SVI
 * gateway holding a collected RIB, preferring one with no collected ACLs — and its default route(s)
 * removed; every other record is the real compiled evidence. Vitest isolates modules per file.
 *
 * Moved here from engine.test.ts ("no route is a drop, and it cites the RIB it searched", and the
 * no-route half of "records the ACL gap at a hop that STOPS the trace"): on the old sample core2 carried
 * no default route; on the regenerated one it does, so those assertions pinned a table that no longer
 * exists. They are kept verbatim in substance, on a table that has the property they are about.
 */
import { describe, expect, it, vi } from "vitest";

interface RouteRow {
  prefix: string;
  nextHop: string | null;
  source: string | null;
  cite: string;
}
interface FabricShape {
  routes: Record<string, RouteRow[]>;
  l3: { host: string | null; sviIp: string | null; fhrpRole: string | null }[];
  coverage: { aclHosts: string[] };
}

const cf = vi.hoisted(() => ({ host: null as string | null, removed: [] as RouteRow[] }));

vi.mock("../data/fabric.json", async () => {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const active = c.l3.filter((r) => r.host !== null && (r.fhrpRole ?? "").toLowerCase() === "active" && c.routes[r.host] !== undefined);
  const withDefault = active.filter((r) => c.routes[r.host!]!.some((x) => x.prefix === "0.0.0.0/0"));
  const pick = withDefault.find((r) => !c.coverage.aclHosts.includes(r.host!)) ?? withDefault[0];
  if (pick === undefined) throw new Error("precondition: some observed-Active SVI gateway must hold a collected RIB with a default route");
  cf.host = pick.host;
  cf.removed = c.routes[pick.host!]!.filter((x) => x.prefix === "0.0.0.0/0");
  c.routes[pick.host!] = c.routes[pick.host!]!.filter((x) => x.prefix !== "0.0.0.0/0");
  return { default: c };
});

import { claimBadge, T1_verdict } from "../core/claims";
import { fabric, routesOf } from "../core/data";
import { ribIncompleteness } from "./rib-completeness";
import { suggestedFlows, traceFlow, unobservedPolicyInputs } from "./engine";

const host = (): string => {
  expect(cf.host, "precondition: the fixture chose a gateway").not.toBeNull();
  return cf.host!;
};

describe("the fixture changes one thing", () => {
  it("removes exactly the chosen gateway's default route(s), and nothing else about its table", () => {
    const h = host();
    expect(cf.removed.length).toBeGreaterThan(0);
    expect(routesOf(h).some((r) => r.prefix === "0.0.0.0/0")).toBe(false);
    expect(routesOf(h).length).toBeGreaterThan(0);
  });
});

describe("the no-route preset, offered on a table that really has no default route", () => {
  const s = suggestedFlows().find((f) => f.id === "no-route");

  it("is offered, and its trace is a FIRST-hop no-route at the gateway it names", () => {
    expect(s, "a gateway without a default route yields the preset").toBeDefined();
    const t = traceFlow(s!.flow);
    expect(s!.expectedOutcome).toBe("dropped");
    expect(t.hops.length).toBe(1);
    expect(t.hops[0]!.host).toBe(host());
    expect(t.hops[0]!.verdict).toBe("no-route");
    expect(s!.title.startsWith(`${host()} `)).toBe(true);
  });

  it("states its premise from that hop's own decidedBy, citing the table it searched", () => {
    const t = traceFlow(s!.flow);
    const d = t.hops[0]!.decidedBy!;
    expect(s!.rationale).toContain(d.label);
    expect(s!.rationale).toContain(`(${d.cite})`);
    expect(d.cite).toBe(`routes.${host()}`);
    expect(d.label).toContain("including no default route");
  });
});

describe("no route is a drop, and it cites the RIB it searched (moved from engine.test.ts)", () => {
  const flow = () => suggestedFlows().find((f) => f.id === "no-route")!.flow;

  it("drops with an absence citation naming the searched RIB", () => {
    const trace = traceFlow(flow());
    expect(trace.hops[0]!.host).toBe(host());
    expect(trace.outcome).toBe("dropped");
    expect(trace.hops[0]!.verdict).toBe("no-route");
    expect(trace.hops[0]!.decidedBy?.kind).toBe("absence");
    expect(trace.hops[0]!.decidedBy?.label).toContain(host());
    expect(trace.claim).toContain(`no prefix in its collected RIB (routes.${host()})`);
  });

  it("a host with no collected ACLs stays an unobserved filter at the hop that STOPS the trace", () => {
    const trace = traceFlow(flow());
    const h = host();
    if (fabric.coverage.aclHosts.includes(h)) {
      /* Only when every candidate gateway holds ACLs; then the stop hop's ACLs WERE collected. */
      expect(unobservedPolicyInputs(trace).map((g) => [g.host, g.kind])).not.toContainEqual([h, "acl-uncollected"]);
      return;
    }
    expect(unobservedPolicyInputs(trace).map((g) => [g.host, g.kind])).toContainEqual([h, "acl-uncollected"]);
    expect(T1_verdict(trace)).toMatch(new RegExp(`no ACLs collected for ${h}`));
    expect(trace.caveats.join(" ")).toMatch(new RegExp(`No ACLs were collected for ${h}`));
    expect(claimBadge(trace)).not.toBe("SCOPED");
  });

  it("a drop from a table the snapshot shows incomplete is named as such, not as a decided absence", () => {
    const trace = traceFlow(flow());
    const partial = ribIncompleteness(host()).length > 0;
    expect(unobservedPolicyInputs(trace).some((g) => g.kind === "rib-partial" && g.host === host())).toBe(partial);
    expect(/That drop is not decided/.test(trace.claim)).toBe(unobservedPolicyInputs(trace).some((g) => g.kind === "rib-partial" || g.kind === "ingress-alternate"));
  });
});
