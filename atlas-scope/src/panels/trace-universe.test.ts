/**
 * trace-universe.test.ts — the flow universe the panels tests draw their subjects from covers the class it
 * stands for, on whatever snapshot is loaded.
 *
 * Why (2026-09-28 verifier V1). The universe was every pair of the addresses the SVI records name. That is a
 * hand-chosen stand-in for "where a packet can go", and it was wrong on the engine's golden fleet: core1
 * routes 10.0.0.0/16 off-SVI, the fleet's only decided denial goes there, and a test that searched the
 * universe for "a decided denial" reported the snapshot had none. The route tables are the forwarding
 * denominator, so the invariant is stated over them: every route an ordinary host address can be forwarded
 * by is the chosen route for some destination of the universe.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { parseIpv4 } from "../forwarding/ip";
import { describeGolden } from "../test-support/golden-sample";
import { exercisableRoutes, longestMatchOn, ownedAddressesWithHostRoutes, routedHostAddresses, universeFlows } from "../test-support/trace-universe";

const destinations = (): number[] => [...new Set(universeFlows().map((f) => f.dstIp))].flatMap((a) => {
  const ip = parseIpv4(a);
  return ip === null ? [] : [ip];
});

describe("the flow universe covers the forwarding denominator", () => {
  it("every route an ordinary host address can be forwarded by is chosen for some universe destination", () => {
    const routes = exercisableRoutes();
    expect(routes.length, "precondition: the snapshot has a route an ordinary host address is forwarded by").toBeGreaterThan(0);
    const dsts = destinations();
    const missed = routes
      .filter(({ host, route }) => !dsts.some((ip) => longestMatchOn(host, ip) === route))
      .map(({ host, route, witness }) => `${host} ${route.prefix} (${route.cite}; e.g. ${witness})`);
    expect(missed, "routes no universe destination is forwarded by").toEqual([]);
  });

  it("every routed destination it adds is an ordinary host address, never a device's own", () => {
    const owned = ownedAddressesWithHostRoutes();
    for (const r of routedHostAddresses()) {
      expect(owned.has(r.ip), `${r.ip} is a device address`).toBe(false);
      expect(longestMatchOn(r.host, parseIpv4(r.ip)!)?.prefix, `${r.ip} on ${r.host}`).toBe(r.prefix);
    }
  });

  it("each exercisable route's witness is longest-matched to that route on its own host", () => {
    for (const { host, route, witness } of exercisableRoutes()) expect(longestMatchOn(host, parseIpv4(witness)!)).toBe(route);
    expect(Object.keys(fabric.routes).length).toBeGreaterThan(0);
  });
});

describeGolden("the routed destinations of the reference sample", () => {
  it("adds exactly one host inside core1's off-SVI 10.0.0.0/16 (the /30 transit links have no ordinary host)", () => {
    expect(routedHostAddresses().map((r) => `${r.host} ${r.prefix} ${r.ip}`)).toEqual(["core1 10.0.0.0/16 10.0.0.50"]);
  });
});
