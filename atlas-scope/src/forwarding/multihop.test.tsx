/**
 * multihop.test.tsx — hop-by-hop, on the data's own multi-hop edges, and the one branch the data still
 * cannot reach: a routing loop.
 *
 * HISTORY. On the old sample the maximum trace depth was 1 and no collected route named an address a
 * collected host owns, so every piece of machinery that makes a path a path — the second iteration of the
 * hop loop, `resolveNextHost`, the `visited` loop detector, and a rendered list with more than one row —
 * ran only here, on a fixture that re-pointed core1's 10.0.0.0/16 summary at core2. The regenerated sample
 * (phase 3) has real multi-hop edges, so the second hop, `resolveNextHost` and the rendered multi-row list
 * now run on REAL traces here, with every subject resolved by PROPERTY from the loaded fabric:
 *
 *   A REAL EDGE is a collected host A, a route of A whose next hop another collected host B owns, and a
 *   source address in one of A's SVI subnets whose observed ingress (the engine's own `ingressCandidates`,
 *   the one owner of that ranking) IS A. Name order decides nothing: on an isomorphic rename the host that
 *   sorts first may be an FHRP Standby, which is not where that source enters (2026-09-28 verifier, D1).
 *
 * WHAT IS STILL FIXTURE, stated plainly because it decides what this proves: the collected routes form no
 * loop, so the `visited` detector still has no real trace. The fixture ADDS route records and nothing else:
 *   - on a real edge, exactly ONE record at B — a /32 inside A's route's prefix, pointing back at an address
 *     A owns on a subnet B is connected to — so a flow to that /32 runs A -> B -> A;
 *   - on a fabric with no real edge (the engine's 7-device golden snapshot has none), TWO records — the same
 *     /32 at A pointing at B's address on a subnet they share, and at B pointing back at A's — so the loop
 *     detector still runs there.
 * The first test proves the fixture is exactly those records by removing them and byte-comparing against the
 * real data. Every flow other than one to that /32 traces exactly as on the real data.
 *
 * The records are added in `beforeAll`, after the engine has loaded, because choosing A needs the engine's
 * ingress ranking. That is sound because a static route feeds no index the engine builds at load (the address
 * owners read SVI, FHRP and LOCAL /32 records only; routes are read per trace through `routesOf`), and no
 * trace runs before the records are in place.
 *
 * A fabric with neither a real edge nor two routed hosts sharing a subnet makes the dependent tests NOT
 * APPLICABLE by name (./test-subjects.ts); on the reference sample an absent subject is a failure.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { need } from "./test-subjects";

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
  l3: { host: string | null; sviIp: string | null; vip: string | null; fhrpRole: string | null }[];
}
interface Edge {
  a: string;
  b: string;
  route: RouteRow;
  /** An address A owns (not B) on a subnet B is directly connected to: where B would hand the packet back. */
  backTo: string;
}
interface Pair {
  a: string;
  b: string;
  /** B's own address on a subnet both hosts are connected to, and A's. */
  toB: string;
  toA: string;
}

/* Everything the fixture resolves, hoisted with the mock factory (which runs before this file's bindings). */
const fx = vi.hoisted(() => {
  const toInt = (ip: string): number => ip.split(".").reduce((n, o) => ((n << 8) | Number(o)) >>> 0, 0);
  const toIp = (n: number): string => [24, 16, 8, 0].map((s) => (n >>> s) & 255).join(".");
  const prefixOf = (p: string): { base: number; bits: number } | null => {
    const m = /^(\d+\.\d+\.\d+\.\d+)\/(\d+)$/.exec(p);
    return m === null ? null : { base: toInt(m[1]!), bits: Number(m[2]) };
  };
  const contains = (p: { base: number; bits: number }, ip: string): boolean =>
    p.bits === 0 || toInt(ip) >>> (32 - p.bits) === p.base >>> (32 - p.bits);
  /** ip -> hosts that own it: SVI address, FHRP virtual address, RIB local /32. */
  const owners = (f: FabricShape): Map<string, Set<string>> => {
    const m = new Map<string, Set<string>>();
    const add = (ip: string, h: string): void => {
      const s = m.get(ip) ?? new Set<string>();
      s.add(h);
      m.set(ip, s);
    };
    for (const r of f.l3) {
      if (r.host === null) continue;
      const a = r.sviIp?.trim().split(/[\s/]/)[0];
      if (a) add(a, r.host);
      if (r.vip !== null) add(r.vip, r.host);
    }
    for (const [h, rs] of Object.entries(f.routes)) for (const r of rs) if (r.source === "local" && r.prefix.endsWith("/32")) add(r.prefix.slice(0, -3), h);
    return m;
  };
  /** Addresses `h` alone owns (never an FHRP address shared with another host) inside a connected subnet of `on`. */
  const soleAddressesOn = (f: FabricShape, own: Map<string, Set<string>>, h: string, on: string): string[] => {
    const conn = f.routes[on]!.filter((x) => x.source === "connected").map((x) => fx0.prefixOf(x.prefix));
    return [...own.entries()]
      .filter(([, hs]) => hs.size === 1 && hs.has(h))
      .map(([ip]) => ip)
      .filter((ip) => conn.some((p) => p !== null && fx0.contains(p, ip)))
      .sort();
  };
  const fx0 = {
    toInt,
    toIp,
    prefixOf,
    contains,
    owners,
    soleAddressesOn,
    /** The mocked document (the SAME object the engine reads), every real edge, and every routed pair. */
    clone: null as FabricShape | null,
    edges: [] as Edge[],
    pairs: [] as Pair[],
    /** Set in beforeAll: the records the fixture added, as [host, record]. */
    added: [] as [string, RouteRow][],
  };
  return fx0;
});

vi.mock("../data/fabric.json", async () => {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const own = fx.owners(c);
  const routed = Object.keys(c.routes).sort();
  for (const a of routed) {
    for (const r of c.routes[a]!) {
      if (r.nextHop === null) continue;
      const p = fx.prefixOf(r.prefix);
      if (p === null || p.bits === 0 || p.bits >= 31) continue;
      for (const b of [...(own.get(r.nextHop) ?? [])].filter((h) => h !== a && c.routes[h] !== undefined).sort()) {
        const backTo = fx.soleAddressesOn(c, own, a, b)[0];
        if (backTo !== undefined) fx.edges.push({ a, b, route: r, backTo });
      }
    }
  }
  for (const a of routed)
    for (const b of routed) {
      if (a === b) continue;
      const toB = fx.soleAddressesOn(c, own, b, a)[0];
      const toA = fx.soleAddressesOn(c, own, a, b)[0];
      if (toB !== undefined && toA !== undefined) fx.pairs.push({ a, b, toB, toA });
    }
  fx.clone = c;
  return { default: c };
});

let realFabric: FabricShape;
let traceFlow: typeof import("./engine").traceFlow;
let TTL_LIMIT: number;
let HopList: typeof import("../panels/HopList").HopList;
type Probe = { srcIp: string; dstIp: string; protocol: "tcp"; dstPort: number; srcPort: null };
/** The real edge and the flow that crosses it; undefined on a fabric that has none. */
let edge: (Edge & { flow: Probe }) | undefined;
/** The loop the fixture builds (on the real edge when there is one), and the flow into it. */
let loop: { a: string; b: string; flow: Probe } | undefined;

beforeAll(async () => {
  realFabric = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const engine = await import("./engine");
  const ip = await import("./ip");
  traceFlow = engine.traceFlow;
  TTL_LIMIT = engine.TTL_LIMIT;
  HopList = (await import("../panels/HopList")).HopList;
  const c = fx.clone!;
  const own = fx.owners(c);

  /* A source address in one of `host`'s SVI subnets whose observed ingress, ranked by the engine, IS `host`. */
  const sourceEnteringAt = (host: string): string | undefined => {
    for (const r of c.l3.filter((x) => x.host === host && x.sviIp !== null)) {
      const a = ip.parseInterfaceAddress(r.sviIp!);
      if (a === null) continue;
      for (const off of [50, 60, 70, 100]) {
        const h = ip.hostAddressIn(a.prefix, off);
        if (h !== null && !own.has(ip.formatIpv4(h)) && engine.ingressCandidates(h)[0]?.host === host) return ip.formatIpv4(h);
      }
    }
    return undefined;
  };
  /* A destination inside the route's prefix that A's own longest-prefix match sends by THAT route. */
  const dstVia = (e: Edge): string | undefined => {
    const p = ip.parsePrefix(e.route.prefix)!;
    for (const off of [10, 20, 77, 100, 200]) {
      const d = ip.hostAddressIn(p, off);
      if (d !== null && !own.has(ip.formatIpv4(d)) && engine.chooseRoute(e.a, d)?.winner.cite === e.route.cite) return ip.formatIpv4(d);
    }
    return undefined;
  };

  for (const e of fx.edges) {
    const src = sourceEnteringAt(e.a);
    const dst = dstVia(e);
    if (src === undefined || dst === undefined) continue;
    edge = { ...e, flow: { srcIp: src, dstIp: dst, protocol: "tcp", dstPort: 443, srcPort: null } };
    break;
  }

  if (edge !== undefined) {
    /* A /32 in the route's prefix that A reaches by that same route and nothing owns: B sends it back to A. */
    const p = ip.parsePrefix(edge.route.prefix)!;
    const loopDst = [77, 78, 79, 177]
      .map((off) => ip.hostAddressIn(p, off))
      .filter((d): d is number => d !== null)
      .map((d) => ip.formatIpv4(d))
      .find((d) => !own.has(d) && engine.chooseRoute(edge!.a, ip.parseIpv4(d)!)?.winner.cite === edge!.route.cite);
    if (loopDst !== undefined) {
      fx.added = [[edge.b, { prefix: `${loopDst}/32`, nextHop: edge.backTo, outIntf: null, source: "static", adminDistance: 1, cite: `routes.${edge.b}[fixture]` }]];
      loop = { a: edge.a, b: edge.b, flow: { ...edge.flow, dstIp: loopDst } };
    }
  }
  if (loop === undefined) {
    for (const pr of fx.pairs) {
      const src = sourceEnteringAt(pr.a);
      if (src === undefined) continue;
      /* RFC 2544 benchmarking space: no collected route or address of a real fleet is in it. */
      const loopDst = "198.18.0.77";
      fx.added = [
        [pr.a, { prefix: `${loopDst}/32`, nextHop: pr.toB, outIntf: null, source: "static", adminDistance: 1, cite: `routes.${pr.a}[fixture]` }],
        [pr.b, { prefix: `${loopDst}/32`, nextHop: pr.toA, outIntf: null, source: "static", adminDistance: 1, cite: `routes.${pr.b}[fixture]` }],
      ];
      loop = { a: pr.a, b: pr.b, flow: { srcIp: src, dstIp: loopDst, protocol: "tcp", dstPort: 443, srcPort: null } };
      break;
    }
  }
  for (const [h, r] of fx.added) c.routes[h]!.push(r);
});

const EDGE = "route whose next hop another collected host owns, crossed by a source that enters at the route's host";
const LOOP = "pair of routed hosts on which a two-record routing loop can be built";

/* ── DOM harness ───────────────────────────────────────────────────────────── */

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

/* ── the fixture is honest about itself ────────────────────────────────────── */

describe("the fixture", () => {
  it("adds exactly the route records it names to the real compiled data, and nothing else", (ctx) => {
    need(ctx, loop, LOOP);
    const restored = structuredClone(fx.clone!);
    // One record on a real edge, two otherwise — never more.
    expect(fx.added.length).toBe(edge !== undefined && loop!.a === edge.a && loop!.b === edge.b ? 1 : 2);
    for (const [h, r] of [...fx.added].reverse()) {
      expect(restored.routes[h]!.at(-1)).toEqual(r);
      restored.routes[h]!.pop();
    }
    // Byte-identical once those records are taken out: nothing else about the data is fixture.
    expect(JSON.stringify(restored)).toBe(JSON.stringify(realFabric));
  });

  it("builds on a REAL multi-hop edge: a collected route of A whose next hop B, another collected host, owns", (ctx) => {
    const e = need(ctx, edge, EDGE);
    const own = fx.owners(realFabric);
    expect(own.get(e.route.nextHop!)?.has(e.b)).toBe(true);
    expect(Object.keys(realFabric.routes)).toContain(e.a);
    expect(Object.keys(realFabric.routes)).toContain(e.b);
    expect(realFabric.routes[e.a]!.some((r) => r.cite === e.route.cite)).toBe(true);
    // The address B hands the loop back to is one A alone owns.
    expect([...(own.get(e.backTo) ?? [])]).toEqual([e.a]);
  });
});

/* ── the hop loop, past its first iteration — on a real edge ───────────────── */

describe("a trace that takes a second hop", () => {
  it("resolves the next host through the address owners and runs the loop again", (ctx) => {
    const e = need(ctx, edge, EDGE);
    const t = traceFlow(e.flow);

    expect(t.hops.length, "the hop loop must iterate past the first hop").toBeGreaterThan(1);
    const [first, second] = t.hops;
    expect(first?.host).toBe(e.a);
    /* `resolveNextHost` on a real collected route: the branch that turns a route into a path. */
    expect(first?.nextHop).toBe(e.route.nextHop);
    expect(first?.nextHost, "the next-hop address resolves to the host that owns it").toBe(e.b);
    /* A hop the trace continued past either passed (forwarded) or could not be evaluated (unmodeled) —
       never one that stopped the packet. The honesty invariant holds at depth 2 as at depth 1. */
    expect(["forwarded", "unmodeled"]).toContain(first?.verdict);
    expect(first?.decidedBy, "every hop names what decided it").not.toBeNull();

    // The second hop is a real hop: its own host, its own verdict, its own decider.
    expect(second?.index).toBe(1);
    expect(second?.host).toBe(e.b);
    expect(second?.decidedBy, "every hop names what decided it").not.toBeNull();
    // Every hop is indexed and in order, which is what makes the list addressable.
    expect(t.hops.map((h) => h.index)).toEqual(t.hops.map((_, i) => i));
  });

  it("carries a scope claim and a non-empty caveat list on the multi-hop answer too", (ctx) => {
    // B2 is not suspended because the path got longer.
    const t = traceFlow(need(ctx, edge, EDGE).flow);
    expect(t.hops.length).toBeGreaterThan(1);
    expect(t.claim.length).toBeGreaterThan(0);
    expect(t.caveats.length).toBeGreaterThan(0);
  });

  it("detects a routing loop and drops rather than delivering", (ctx) => {
    /* The `visited` branch: still zero executions on the real data, whose routes form no loop. The added
       record(s) make the collected routes describe A -> B -> A for one address, which the model must report
       as a drop — never as a delivery, and never as an unbounded walk. */
    const l = need(ctx, loop, LOOP);
    const t = traceFlow(l.flow);
    expect(t.hops.map((h) => h.host)).toEqual([l.a, l.b, l.a]);
    expect(t.hops.at(-1)?.verdict).toBe("loop");
    expect(t.hops.length, "the loop detector cuts long before the TTL cap").toBeLessThan(TTL_LIMIT);
    expect(t.outcome).toBe("dropped");
    expect(t.caveats.join(" ").toLowerCase()).toContain("loop");
  });
});

/* ── the rendered path ─────────────────────────────────────────────────────── */

describe("the hop list renders more than one hop", () => {
  it("draws a row per hop, each naming its host, and the path's continuation", (ctx) => {
    const e = need(ctx, edge, EDGE);
    const t = traceFlow(e.flow);
    expect(t.hops.length).toBeGreaterThan(1);

    const c = mount(<HopList trace={t} activeIndex={0} onSelect={() => undefined} />);
    const heads = c.querySelectorAll(".hop__head");
    expect(heads.length, "one row per hop, not one row for the first hop").toBe(t.hops.length);

    const text = c.textContent ?? "";
    for (const hop of t.hops) expect(text).toContain(hop.host);
    // The thing a one-hop capture can never show: the path continuing to a named next device.
    expect(text).toContain(e.b);
    expect(text).toContain(e.route.nextHop!);
  });

  it("indexes every hop, so a reader can address the second one", (ctx) => {
    const t = traceFlow(need(ctx, edge, EDGE).flow);
    const c = mount(<HopList trace={t} activeIndex={1} onSelect={() => undefined} />);
    const heads = [...c.querySelectorAll<HTMLElement>(".hop__head")];
    expect(heads.length).toBe(t.hops.length);
    expect(heads[1]?.dataset["hopIndex"]).toBe("1");
  });
});
