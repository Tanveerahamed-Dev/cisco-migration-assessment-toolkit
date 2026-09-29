/**
 * rib-partial-route.test.ts — a route CHOSEN from a table the snapshot shows to be incomplete is not
 * a decided basis for an outcome (2026-09-22 critic, B1 blocker).
 *
 * The critic's case: core1's table held no OSPF route although its OSPF adjacency with router 10.0.99.2 was
 * FULL; the static 10.0.0.0/16 summary won the lookup, egress resolved to Vlan30, and PROTECT_SERVERS "deny
 * ip any any" was returned as a decided (REFUTED) denial with no word of the incompleteness. The sweep below
 * runs real engine output over a grid of flows and asserts the class, not the one flow.
 *
 * The fleet (one, since phase 3): the regenerated reference sample gives that session its realistic L3 home
 * (owner decision O2; the phase-2.75 correction, open-issues O65 — the "transit SVI VLAN 900" of earlier
 * notes was retired then): it runs over Vlan10, 10.0.10.2 <-> 10.0.10.3 (routing_neighbors.core1.ospf[0]
 * records neighbour address 10.0.10.3 on Vlan10), an SVI both cores' tables hold as connected. So core1's
 * table is not contradicted by that session, and the critic's flow is decided on evidence where nothing
 * else leaves core1's table open.
 *
 * The critic's flow is still pinned as an EQUIVALENCE, not as an outcome — undetermined exactly when
 * core1's table is shown incomplete, and the session a reason exactly when its link is missing — so the pin
 * holds whichever way the evidence about that table falls, and no fleet can pass by reading another's
 * premise. A per-family check once let dist1's OSPF routes vouch for 10.0.99.2 and brought this false
 * decision back (2026-09-26 verifier, E2-V1); an earlier revision of this file moved these assertions into a
 * counterfactual, which hid that. They stay on real data.
 *
 * TWO TIERS. The sweeps are invariants over whatever fabric is loaded: their probes are DERIVED from the data
 * (a host in every observed SVI subnet and in every routed prefix, every routing neighbour's router ID and
 * link address, and two addresses outside every collected prefix), never typed sample addresses. The
 * critic's flow names the sample's host, neighbour and addresses, so it is golden and reads them from
 * ./golden-expectations.ts.
 */
import { describe, expect, it } from "vitest";
import { describeGolden } from "../test-support/golden-sample";

import evidenceJson from "./rib-evidence.json";
import { bandOfTrace } from "../core/claims";
import { fabric, routesOf } from "../core/data";
import type { Flow, Trace } from "../core/types";
import { traceFlow, unobservedPolicyInputs } from "./engine";
import { GOLDEN_FORWARDING } from "./golden-expectations";
import { formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4, parsePrefix, prefixContains } from "./ip";
import { ribIncompleteness } from "./rib-completeness";
import { lazy, needSome } from "./test-subjects";

type Adjacency = { neighbor: string | null; state: string | null; cite: string; address?: string | null; interface?: string | null };
const EVIDENCE = evidenceJson as unknown as { hosts: Record<string, { adjacencies: Adjacency[] }> };

/** Two addresses outside every collected prefix but the default: documentation / public space, not sample data. */
const OFF_FABRIC = ["198.51.100.7", "8.8.8.8"];

/** The probe grid, derived from the loaded fabric. */
const PROBES = lazy((): Flow[] => {
  const srcs = new Set<string>();
  const dsts = new Set<string>(OFF_FABRIC);
  const subnets = new Set<string>();
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (a === null) continue;
    const key = `${a.prefix.base}/${a.prefix.bits}`;
    if (subnets.has(key)) continue;
    subnets.add(key);
    for (const [set, off] of [[srcs, 50], [dsts, 10], [dsts, 50]] as const) {
      const h = hostAddressIn(a.prefix, off);
      if (h !== null) set.add(formatIpv4(h));
    }
  }
  for (const rs of Object.values(fabric.routes))
    for (const r of rs) {
      const p = parsePrefix(r.prefix);
      if (p === null || p.bits === 0) continue;
      const h = hostAddressIn(p, 20);
      if (h === null) continue;
      dsts.add(formatIpv4(h));
      // A source inside a routed prefix no observed subnet holds (the old grid's 10.0.99.9 / 10.0.50.50 class).
      if (![...fabric.l3].some((x) => {
        const a = x.sviIp === null ? null : parseInterfaceAddress(x.sviIp);
        return a !== null && prefixContains(a.prefix, h);
      })) srcs.add(formatIpv4(h));
    }
  for (const { adjacencies } of Object.values(EVIDENCE.hosts))
    for (const a of adjacencies) for (const ip of [a.neighbor, a.address ?? null]) if (ip !== null && parseIpv4(ip) !== null) dsts.add(ip);
  const out: Flow[] = [];
  for (const s of [...srcs].sort())
    for (const d of [...dsts].sort())
      for (const [protocol, dstPort] of [["tcp", 443], ["tcp", 80], ["udp", 53], ["icmp", null], ["ip", null], ["tcp", 22], ["udp", 161], ["tcp", 3389]] as const)
        if (s !== d) out.push({ srcIp: s, dstIp: d, protocol, dstPort, srcPort: null } as Flow);
  return out;
});
const TRACES = lazy((): Trace[] => PROBES().map(traceFlow));

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
  it("sweep: no REFUTED or RESOLVED trace rests on a non-connected route at a host whose table is shown incomplete, unless the gap is named", (ctx) => {
    let checked = 0;
    for (const t of TRACES()) {
      const flow = t.flow;
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
    // Required on the reference sample; on a fleet where no chosen route comes from an incomplete table, named.
    needSome(ctx, checked, "trace resting on a non-connected route from a table shown incomplete");
  });

  it("B1's real-data home, on whichever fleet this is: a flow that rests on a non-connected route from an incomplete table is UNDETERMINED and names that table in its caveats", (ctx) => {
    const homes = new Set<string>();
    for (const t of TRACES()) {
      const flow = t.flow;
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
    needSome(ctx, homes.size, "incomplete table whose chosen route is shown undetermined");
  });
});

/* Golden (phase 3): the critic's flow names the reference sample's host, neighbour and addresses. */
describeGolden("a route chosen from an incomplete table — the critic's flow", () => {
  const G = GOLDEN_FORWARDING.ribPartialRoute;

  it("the critic's flow is UNDETERMINED exactly when its host's table is shown incomplete, and the named session is a reason exactly when its link is missing", () => {
    // The session the critic named, found by its neighbour (the router ID), not by a position.
    const adj = (EVIDENCE.hosts[G.host]?.adjacencies ?? []).filter((a) => a.neighbor === G.neighborRouterId && /^full/i.test(a.state ?? ""));
    expect(adj, `${G.host} records exactly one FULL session with ${G.neighborRouterId}`).toHaveLength(1);
    const a = adj[0]!;
    expect(a.interface).toBe(G.sessionInterface);
    const addr = parseIpv4(a.address ?? a.neighbor ?? "");
    expect(addr).not.toBeNull();
    const intfKey = (s: string) => {
      const m = /^([a-z-]+)\s*(\S+)$/i.exec(s.trim());
      return m === null ? s.toLowerCase() : `${m[1]!.slice(0, 2).toLowerCase()}${m[2]!.toLowerCase()}`;
    };
    const linkHeld = routesOf(G.host).some((r) => {
      const p = parsePrefix(r.prefix);
      return r.source === "connected" && r.outIntf !== null && a.interface != null
        && intfKey(r.outIntf) === intfKey(a.interface) && p !== null && prefixContains(p, addr!);
    });
    const reasons = ribIncompleteness(G.host);
    expect(reasons.map((r) => r.cite).includes(a.cite), `${a.cite} is a reason iff its link is missing`).toBe(!linkHeld);

    const incomplete = reasons.length > 0;
    const t = traceFlow(G.criticFlow);
    expect(t.outcome).toBe(G.criticOutcome);
    expect(bandOfTrace(t) === "UNDETERMINED", `undetermined iff ${G.host}'s table is shown incomplete`).toBe(incomplete);
    expect(unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial" && g.host === G.host)).toBe(incomplete);
    expect(t.claim.includes(INCOMPLETE(G.host))).toBe(incomplete);
    expect(t.caveats.some((c) => c.includes(INCOMPLETE(G.host)))).toBe(incomplete);
  });
});
