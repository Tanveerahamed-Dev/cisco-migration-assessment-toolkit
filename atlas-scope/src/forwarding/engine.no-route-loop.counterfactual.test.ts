/**
 * engine.no-route-loop.counterfactual.test.ts — the "no-route" preset never asserts a fact its trace did not
 * check (disc-app-sample-assumptions #2).
 *
 * The defect: the preset's rationale was written BEFORE the trace ran ("<gateway> ... its collected RIB
 * holds no default route") and `take()` accepted ANY dropped outcome. A drop also comes from a routing loop
 * at a later hop, from the hop cap, or from a no-route at another host — and each of those carried the same
 * sentence about a table that does hold a default route.
 *
 * The counterfactual, resolved by PROPERTY on the real compiled fabric: an observed-Active SVI gateway A
 * with a default route, and another collected host B that owns an address inside one of A's connected
 * subnets. A's default is pointed at B, and B's default at A — two default routes pointing at each other,
 * which is the loop the discovery report reproduced (core1 -> core2 -> core1 on the reference sample).
 */
import { describe, expect, it, vi } from "vitest";

interface RouteRow {
  prefix: string;
  nextHop: string | null;
  outIntf: string | null;
  source: string | null;
  adminDistance: number | null;
  cite: string;
}
interface FabricShape {
  routes: Record<string, RouteRow[]>;
  l3: { host: string | null; sviIp: string | null; fhrpRole: string | null }[];
}

const cf = vi.hoisted(() => ({ a: null as string | null, b: null as string | null, aAddr: null as string | null, bAddr: null as string | null }));

/* Hoisted with the mock factory, which runs before any top-level binding of this file exists. */
const net = vi.hoisted(() => {
  /** "10.0.10.2 255.255.255.0" or "10.0.10.3/24" -> [address, prefix length]. */
  const svi = (ip: string): [string, number] | null => {
    const m = /^(\d+\.\d+\.\d+\.\d+)(?:\/(\d+)|\s+(\d+\.\d+\.\d+\.\d+))$/.exec(ip.trim());
    if (m === null) return null;
    const bits = m[2] !== undefined ? Number(m[2]) : m[3]!.split(".").map(Number).reduce((n, o) => n + (o >>> 0).toString(2).split("1").length - 1, 0);
    return [m[1]!, bits];
  };
  const toInt = (ip: string): number => ip.split(".").reduce((n, o) => ((n << 8) | Number(o)) >>> 0, 0);
  const sameSubnet = (a: string, b: string, bits: number): boolean => bits === 0 || toInt(a) >>> (32 - bits) === toInt(b) >>> (32 - bits);
  return { svi, sameSubnet };
});

vi.mock("../data/fabric.json", async () => {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const { svi, sameSubnet } = net;
  for (const a of c.l3) {
    if (a.host === null || a.sviIp === null || (a.fhrpRole ?? "").toLowerCase() !== "active") continue;
    const ra = c.routes[a.host];
    if (ra === undefined || !ra.some((r) => r.prefix === "0.0.0.0/0")) continue;
    const aa = svi(a.sviIp);
    if (aa === null) continue;
    const b = c.l3.find((x) => x.host !== null && x.host !== a.host && x.sviIp !== null && c.routes[x.host] !== undefined && svi(x.sviIp) !== null && sameSubnet(svi(x.sviIp)![0], aa[0], aa[1]));
    if (b === undefined) continue;
    const bb = svi(b.sviIp!)!;
    for (const r of ra) if (r.prefix === "0.0.0.0/0") r.nextHop = bb[0];
    const rb = c.routes[b.host!]!;
    const bDefault = rb.filter((r) => r.prefix === "0.0.0.0/0");
    if (bDefault.length > 0) for (const r of bDefault) r.nextHop = aa[0];
    else rb.push({ prefix: "0.0.0.0/0", nextHop: aa[0], outIntf: null, source: "static", adminDistance: 1, cite: `routes.${b.host}[fixture]` });
    cf.a = a.host;
    cf.b = b.host;
    cf.aAddr = aa[0];
    cf.bAddr = bb[0];
    break;
  }
  if (cf.a === null) throw new Error("precondition: an Active SVI gateway with a default route and another collected host on one of its subnets");
  return { default: c };
});

import { routesOf } from "../core/data";
import { suggestedFlows, traceFlow } from "./engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "./ip";
import { fabric } from "../core/data";

describe("two default routes pointing at each other", () => {
  it("precondition: the fixture really built the loop, and the candidate the preset used to take is a LOOP drop", () => {
    expect(routesOf(cf.a!).find((r) => r.prefix === "0.0.0.0/0")?.nextHop).toBe(cf.bAddr);
    expect(routesOf(cf.b!).find((r) => r.prefix === "0.0.0.0/0")?.nextHop).toBe(cf.aAddr);
    const rec = fabric.l3.find((r) => r.host === cf.a && (r.fhrpRole ?? "").toLowerCase() === "active")!;
    const src = formatIpv4(hostAddressIn(parseInterfaceAddress(rec.sviIp!)!.prefix, 50)!);
    const t = traceFlow({ srcIp: src, dstIp: "198.51.100.7", protocol: "tcp", dstPort: 443, srcPort: null });
    expect(t.outcome, "a loop is reported as a drop").toBe("dropped");
    expect(t.hops.at(-1)?.verdict).toBe("loop");
    expect(t.hops.length).toBeGreaterThan(1);
  });

  it("no preset says a table 'holds no default route' — or any no-route premise — about a gateway whose trace did not stop there", () => {
    const presets = suggestedFlows();
    for (const s of presets.filter((p) => p.id === "no-route")) {
      const t = traceFlow(s.flow);
      expect(t.hops.length, s.rationale).toBe(1);
      expect(t.hops[0]!.verdict, s.rationale).toBe("no-route");
      expect(routesOf(t.hops[0]!.host).some((r) => r.prefix === "0.0.0.0/0"), s.rationale).toBe(false);
    }
    /* The class: no rationale on ANY preset asserts a missing default route of a host that holds one. */
    for (const s of presets) {
      const m = /^(\S+) is the observed active gateway/.exec(s.rationale);
      if (m === null) continue;
      if (/no default route/.test(s.rationale)) expect(routesOf(m[1]!).some((r) => r.prefix === "0.0.0.0/0"), s.rationale).toBe(false);
    }
    expect(presets.length).toBeGreaterThan(0);
  });
});
