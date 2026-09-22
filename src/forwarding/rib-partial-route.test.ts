/**
 * rib-partial-route.test.ts — a route CHOSEN from a table the snapshot shows to be incomplete is not
 * a decided basis for an outcome (2026-09-22 critic, B1 blocker).
 *
 * core1's table holds no OSPF route although its OSPF adjacency with 10.0.99.2 is FULL; the static
 * 10.0.0.0/16 summary won the lookup, egress resolved to Vlan30, and PROTECT_SERVERS "deny ip any
 * any" was returned as a decided (REFUTED) denial with no word of the incompleteness. The sweep below
 * runs real engine output over a grid of flows and asserts the class, not the one flow.
 */
import { describe, expect, it } from "vitest";

import { bandOfTrace } from "../core/claims";
import { routesOf } from "../core/data";
import type { Flow } from "../core/types";
import { traceFlow, unobservedPolicyInputs } from "./engine";
import { ribIncompleteness } from "./rib-completeness";

const SRCS = ["10.0.10.50", "10.0.20.50", "10.0.30.50", "10.0.40.50", "10.0.50.50", "10.0.99.9", "10.0.60.50"];
const DSTS = ["10.0.99.2", "10.0.40.20", "10.0.50.1", "10.0.30.10", "10.0.30.50", "8.8.8.8", "198.51.100.7", "10.0.10.20"];
const PROTOS: Flow[] = [];
for (const s of SRCS)
  for (const d of DSTS)
    for (const [protocol, dstPort] of [["tcp", 443], ["tcp", 80], ["udp", 53], ["icmp", null], ["ip", null], ["tcp", 22], ["udp", 161], ["tcp", 3389]] as const)
      PROTOS.push({ srcIp: s, dstIp: d, protocol, dstPort, srcPort: null } as Flow);

/** The route a hop followed, read from its own route evidence cite. */
function followedRoute(host: string, cites: string[]) {
  const rs = routesOf(host);
  for (const c of cites) {
    const r = rs.find((x) => x.cite === c);
    if (r !== undefined) return r;
  }
  return null;
}

describe("a route chosen from an incomplete table never decides an outcome silently", () => {
  it("the critic's flow is UNDETERMINED and names core1's incompleteness in claim and caveats", () => {
    const t = traceFlow({ srcIp: "10.0.30.50", dstIp: "10.0.99.2", protocol: "tcp", dstPort: 443, srcPort: null } as Flow);
    expect(ribIncompleteness("core1").length).toBeGreaterThan(0);
    expect(t.outcome).toBe("denied");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial" && g.host === "core1")).toBe(true);
    expect(t.claim).toContain("core1's collected routing table is itself incomplete");
    expect(t.caveats.some((c) => c.includes("core1's collected routing table is itself incomplete"))).toBe(true);
  });

  it("sweep: no REFUTED or RESOLVED trace rests on a non-connected route at a host whose table is shown incomplete, unless the gap is named", () => {
    let checked = 0;
    for (const flow of PROTOS) {
      const t = traceFlow(flow);
      const band = bandOfTrace(t);
      for (const h of t.hops) {
        if (ribIncompleteness(h.host).length === 0) continue;
        const r = followedRoute(h.host, h.evidence.filter((e) => e.kind === "route").map((e) => e.cite));
        if (r === null || r.source === "connected" || r.source === "local") continue;
        if (h.verdict === "no-route" || h.verdict === "unmodeled") continue;
        checked += 1;
        const named = unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial" && g.host === h.host);
        const inboundDenial = h.verdict === "denied" && h.evidence.some((e) => / inbound \(observed /.test(e.label));
        if (band === "REFUTED" || band === "RESOLVED") {
          expect(named || inboundDenial, `${flow.srcIp}>${flow.dstIp} ${flow.protocol}/${flow.dstPort} at ${h.host} via ${r.cite}`).toBe(true);
        }
        if (named) expect(t.caveats.some((c) => c.includes(`${h.host}'s collected routing table is itself incomplete`))).toBe(true);
      }
    }
    expect(checked, "the sweep must exercise at least one route from an incomplete table").toBeGreaterThan(0);
  });
});
