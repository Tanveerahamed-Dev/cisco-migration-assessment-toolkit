/**
 * multihop.test.tsx — the half of "hop-by-hop" this snapshot cannot reach.
 *
 * THE PROBLEM THIS FILE EXISTS FOR. Measured over the whole reachable flow space of the shipped
 * data, the maximum trace depth is 1 and `resolvedNextHops` is 0. `engine.test.ts` ratchets that
 * honestly and names the branches it therefore cannot cover. But A2 asks for a HOP-BY-HOP result,
 * and until this file existed every piece of machinery that makes a path a path — the second
 * iteration of the hop loop, `resolveNextHost`, the `visited` loop detector, and a rendered list
 * with more than one row in it — had never executed, in the suite or in the product. A criterion
 * graded on a one-hop capture is being graded on the easy half.
 *
 * WHAT IS REAL AND WHAT IS FIXTURE, stated plainly because it decides what this proves:
 *   · REAL: the engine, every branch under test, and the whole compiled fabric — devices, links,
 *     L3 interfaces, endpoints, ACLs, coverage, and both collected routing tables.
 *   · FIXTURE: exactly ONE field. `core1`'s 10.0.0.0/16 static route points at 10.0.30.254, which
 *     is not a collected host; here it points at core2's Vlan20 address, which IS one — read out
 *     of the real `l3` table rather than typed in. The first test below proves the mutation is
 *     that one field by restoring it and byte-comparing against the real data.
 *
 * This does NOT license grading A2's multi-hop half as PASS on the product; `docs/acceptance.md`
 * says so in the A2 row. It makes the machinery executable and regression-guarded, which is a
 * different and smaller claim.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

interface RouteRow {
  prefix: string;
  nextHop: string | null;
  cite: string;
}
interface FabricShape {
  routes: Record<string, RouteRow[]>;
  l3: { host: string; sviIp: string | null }[];
}

const SUMMARY_PREFIX = "10.0.0.0/16";

/** The address of a host's first collected SVI, read from the real L3 table, never typed in. */
function sviOf(f: FabricShape, host: string): string {
  const row = f.l3.find((r) => r.host === host && r.sviIp !== null);
  const ip = row?.sviIp?.split(/[\s/]/)[0];
  if (ip === undefined || ip === "") throw new Error(`the real data must carry an SVI for ${host}`);
  return ip;
}

/* The factory is lazy, so it is allowed to do real work: it clones the REAL compiled fabric and
   changes one field of the clone. Nothing else about the data is touched. */
vi.mock("../data/fabric.json", async () => {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const summary = c.routes["core1"]?.find((r) => r.prefix === SUMMARY_PREFIX);
  if (summary === undefined) throw new Error(`the real data must carry core1's ${SUMMARY_PREFIX} route`);
  summary.nextHop = sviOf(real, "core2");
  return { default: c };
});

let realFabric: FabricShape;
let mutated: FabricShape;
let core2Svi: string;
let core1Svi: string;
let traceFlow: typeof import("./engine").traceFlow;
let TTL_LIMIT: number;
let HopList: typeof import("../panels/HopList").HopList;

beforeAll(async () => {
  realFabric = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  mutated = ((await import("../data/fabric.json")) as unknown as { default: FabricShape }).default;
  core2Svi = sviOf(realFabric, "core2");
  core1Svi = sviOf(realFabric, "core1");
  const engine = await import("./engine");
  traceFlow = engine.traceFlow;
  TTL_LIMIT = engine.TTL_LIMIT;
  HopList = (await import("../panels/HopList")).HopList;
});

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

/** 10.0.41.50 sits in dist1's Vlan41 subnet: in scope, and beyond every core1 connected route. */
const FLOW = { srcIp: "10.0.10.50", dstIp: "10.0.41.50", protocol: "tcp", dstPort: 443, srcPort: null } as const;

/* ── the fixture is honest about itself ────────────────────────────────────── */

describe("the fixture", () => {
  it("changes exactly one field of the real compiled data", () => {
    const restored = structuredClone(mutated);
    const row = restored.routes["core1"]?.find((r) => r.prefix === SUMMARY_PREFIX);
    if (row === undefined) throw new Error("unreachable");
    row.nextHop = realFabric.routes["core1"]?.find((r) => r.prefix === SUMMARY_PREFIX)?.nextHop ?? null;
    // Byte-identical once that one field is put back: nothing else about the data is fixture.
    expect(JSON.stringify(restored)).toBe(JSON.stringify(realFabric));
  });

  it("points a collected host's route at another COLLECTED host, which the real data never does", () => {
    const shipped = realFabric.routes["core1"]?.find((r) => r.prefix === SUMMARY_PREFIX);
    expect(shipped?.nextHop, "the shipped route points at an uncollected gateway").toBe("10.0.30.254");
    expect(mutated.routes["core1"]?.find((r) => r.prefix === SUMMARY_PREFIX)?.nextHop).toBe(core2Svi);
    expect(Object.keys(realFabric.routes), "core2 must be a host with a collected RIB").toContain("core2");
  });
});

/* ── the hop loop, past its first iteration ────────────────────────────────── */

describe("a trace that takes a second hop", () => {
  it("resolves the next host through the address owners and runs the loop again", () => {
    const t = traceFlow(FLOW);

    expect(t.hops.length, "the hop loop must iterate past the first hop").toBeGreaterThan(1);
    const [first, second] = t.hops;
    expect(first?.host).toBe("core1");
    /* `resolveNextHost` — ZERO executions on the shipped data, because no collected route names a
       collected next hop. This is the branch that turns a route into a path. */
    expect(first?.nextHop).toBe(core2Svi);
    expect(first?.nextHost, "the next-hop address resolves to the host that owns it").toBe("core2");
    /* The first hop's verdict is `unmodeled`, and that is the RIGHT answer rather than a defect of
       the fixture: core1 holds collected ACLs but the snapshot carries no `ip access-group`
       binding, so whether a list applies to this flow cannot be decided. The honesty invariant
       holds at depth 2 exactly as it does at depth 1 — a hop we cannot model never reads as one
       that passed. What the fixture adds is that the trace CONTINUES past it. */
    expect(first?.verdict).toBe("unmodeled");
    expect(first?.decidedBy, "an unmodelled hop still names what stopped the evaluation").not.toBeNull();

    // The second hop is a real hop: its own host, its own verdict, its own decider.
    expect(second?.index).toBe(1);
    expect(second?.host).toBe("core2");
    expect(second?.decidedBy, "every hop names what decided it").not.toBeNull();
    expect(second?.verdict, "core2 holds no route for this destination").toBe("no-route");
    expect(t.outcome, "absence of a route is never a delivery").not.toBe("delivered");
    // Every hop is indexed and in order, which is what makes the list addressable.
    expect(t.hops.map((h) => h.index)).toEqual(t.hops.map((_, i) => i));
  });

  it("carries a scope claim and a non-empty caveat list on the multi-hop answer too", () => {
    // B2 is not suspended because the path got longer.
    const t = traceFlow(FLOW);
    expect(t.claim.length).toBeGreaterThan(0);
    expect(t.caveats.length).toBeGreaterThan(0);
  });

  it("detects a routing loop and drops rather than delivering", () => {
    /* The `visited` branch: zero executions on the shipped data. Point core2 back at core1 and the
       collected routes describe a loop, which the model must report as a drop — never as a
       delivery, and never as an unbounded walk. */
    const core2Routes = mutated.routes["core2"];
    if (core2Routes === undefined) throw new Error("unreachable");
    core2Routes.push({ prefix: SUMMARY_PREFIX, nextHop: core1Svi, cite: "routes.core2[fixture]" });
    try {
      const t = traceFlow(FLOW);
      expect(t.hops.at(-1)?.verdict).toBe("loop");
      expect(t.hops.length, "the loop detector cuts long before the TTL cap").toBeLessThan(TTL_LIMIT);
      expect(t.outcome).toBe("dropped");
      expect(t.caveats.join(" ").toLowerCase()).toContain("loop");
    } finally {
      core2Routes.pop();
    }
  });
});

/* ── the rendered path ─────────────────────────────────────────────────────── */

describe("the hop list renders more than one hop", () => {
  it("draws a row per hop, each naming its host, and the path's continuation", () => {
    const t = traceFlow(FLOW);
    expect(t.hops.length).toBeGreaterThan(1);

    const c = mount(<HopList trace={t} activeIndex={0} onSelect={() => undefined} />);
    const heads = c.querySelectorAll(".hop__head");
    expect(heads.length, "one row per hop, not one row for the first hop").toBe(t.hops.length);

    const text = c.textContent ?? "";
    for (const hop of t.hops) expect(text).toContain(hop.host);
    // The thing a one-hop capture can never show: the path continuing to a named next device.
    expect(text).toContain("core2");
    expect(text).toContain(core2Svi);
  });

  it("indexes every hop, so a reader can address the second one", () => {
    const t = traceFlow(FLOW);
    const c = mount(<HopList trace={t} activeIndex={1} onSelect={() => undefined} />);
    const heads = [...c.querySelectorAll<HTMLElement>(".hop__head")];
    expect(heads.length).toBe(t.hops.length);
    expect(heads[1]?.dataset["hopIndex"]).toBe("1");
  });
});
