/**
 * rib-partial-route.test.ts — a route CHOSEN from a table the snapshot shows to be incomplete is not
 * a decided basis for an outcome (2026-09-22 critic, B1 blocker).
 *
 * core1's table held no OSPF route although its OSPF adjacency with 10.0.99.2 was FULL; the static
 * 10.0.0.0/16 summary won the lookup, egress resolved to Vlan30, and PROTECT_SERVERS "deny ip any
 * any" was returned as a decided (REFUTED) denial with no word of the incompleteness. The sweep below
 * runs real engine output over a grid of flows and asserts the class, not the one flow.
 *
 * Every assertion here runs on the REAL snapshot, and must keep holding on BOTH sample fleets:
 *  - the committed one, where core1's FULL/DR neighbour 10.0.99.2 sits on the L2 trunk Po1 and core1's
 *    table holds no link to it (routing_neighbors.core1.ospf[0]) — core1 is shown incomplete;
 *  - the substrate fleet (webapp/sample_data/build_sample.py `_add_forwarding_substrate`), where owner
 *    decision O2 gives that session its realistic L3 home, a transit SVI (VLAN 900) both cores' tables
 *    hold — so core1's table is no longer contradicted by it, and the critic's flow is decided on
 *    evidence. B1's real-data home there is core2: OSPF not collected, an EVPN peer's 240 prefixes
 *    not in its table, and a default learned over the transit that the sweep's flows choose.
 * The critic's flow is therefore pinned as an EQUIVALENCE — undetermined exactly when core1's table is
 * shown incomplete, and the 10.0.99.2 session a reason exactly when its link is missing — so neither
 * fleet can pass by reading the other's premise. A per-family check once let dist1's OSPF routes vouch
 * for 10.0.99.2 and brought this false decision back (2026-09-26 verifier, E2-V1); an earlier revision of
 * this file moved these assertions into a counterfactual, which hid that. They stay on real data.
 */
import { describe, expect, it } from "vitest";

import evidenceJson from "./rib-evidence.json";
import { bandOfTrace } from "../core/claims";
import { routesOf } from "../core/data";
import type { Flow } from "../core/types";
import { traceFlow, unobservedPolicyInputs } from "./engine";
import { parseIpv4, parsePrefix, prefixContains } from "./ip";
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

const INCOMPLETE = (h: string) => `${h}'s collected routing table is itself incomplete`;

describe("a route chosen from an incomplete table never decides an outcome silently", () => {
  it("the critic's flow is UNDETERMINED exactly when core1's table is shown incomplete, and the 10.0.99.2 session is a reason exactly when its link is missing", () => {
    const ev = evidenceJson as unknown as {
      hosts: Record<string, { adjacencies: { neighbor: string | null; state: string | null; cite: string; address?: string | null; interface?: string | null }[] }>;
    };
    // The session the critic named, found by its neighbour (the router ID), not by a position.
    const adj = (ev.hosts["core1"]?.adjacencies ?? []).filter((a) => a.neighbor === "10.0.99.2" && /^full/i.test(a.state ?? ""));
    expect(adj, "core1 records exactly one FULL session with 10.0.99.2").toHaveLength(1);
    const a = adj[0]!;
    const addr = parseIpv4(a.address ?? a.neighbor ?? "");
    expect(addr).not.toBeNull();
    const intfKey = (s: string) => {
      const m = /^([a-z-]+)\s*(\S+)$/i.exec(s.trim());
      return m === null ? s.toLowerCase() : `${m[1]!.slice(0, 2).toLowerCase()}${m[2]!.toLowerCase()}`;
    };
    const linkHeld = routesOf("core1").some((r) => {
      const p = parsePrefix(r.prefix);
      return r.source === "connected" && r.outIntf !== null && a.interface != null
        && intfKey(r.outIntf) === intfKey(a.interface) && p !== null && prefixContains(p, addr!);
    });
    const reasons = ribIncompleteness("core1");
    expect(reasons.map((r) => r.cite).includes(a.cite), `${a.cite} is a reason iff its link is missing`).toBe(!linkHeld);

    const incomplete = reasons.length > 0;
    const t = traceFlow({ srcIp: "10.0.30.50", dstIp: "10.0.99.2", protocol: "tcp", dstPort: 443, srcPort: null } as Flow);
    expect(t.outcome).toBe("denied");
    expect(bandOfTrace(t) === "UNDETERMINED", "undetermined iff core1's table is shown incomplete").toBe(incomplete);
    expect(unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial" && g.host === "core1")).toBe(incomplete);
    expect(t.claim.includes(INCOMPLETE("core1"))).toBe(incomplete);
    expect(t.caveats.some((c) => c.includes(INCOMPLETE("core1")))).toBe(incomplete);
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
        if (named) expect(t.caveats.some((c) => c.includes(INCOMPLETE(h.host)))).toBe(true);
      }
    }
    expect(checked, "the sweep must exercise at least one route from an incomplete table").toBeGreaterThan(0);
  });

  it("B1's real-data home, on whichever fleet this is: a flow that rests on a non-connected route from an incomplete table is UNDETERMINED and names that table in its caveats", () => {
    const homes = new Set<string>();
    for (const flow of PROTOS) {
      const t = traceFlow(flow);
      for (const h of t.hops) {
        if (ribIncompleteness(h.host).length === 0) continue;
        const r = followedRoute(h.host, h.evidence.filter((e) => e.kind === "route").map((e) => e.cite));
        if (r === null || r.source === "connected" || r.source === "local") continue;
        if (h.verdict === "no-route" || h.verdict === "unmodeled") continue;
        // Every such trace names the gap and is undetermined (the sweep above forbids a silent decision;
        // this pins the positive case, so the class is exercised on real data, not only guarded).
        const label = `${flow.srcIp}>${flow.dstIp} ${flow.protocol}/${flow.dstPort} at ${h.host} via ${r.cite}`;
        expect(unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial" && g.host === h.host), label).toBe(true);
        expect(t.caveats.some((c) => c.includes(INCOMPLETE(h.host))), label).toBe(true);
        if (bandOfTrace(t) === "UNDETERMINED") homes.add(h.host);
      }
    }
    expect(homes.size, "at least one incomplete table's chosen route is shown undetermined").toBeGreaterThan(0);
  });
});
