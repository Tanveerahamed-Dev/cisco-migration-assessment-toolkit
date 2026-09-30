/**
 * HopList.no-rib.counterfactual.test.tsx — a hop on a host with NO collected RIB is drawn as neither a
 * pass nor a failure, and never implies a RIB was searched.
 *
 * Why a counterfactual (phase 3, 2026-09-28). These tests ran on tcp 10.0.40.50 -> 10.0.30.10:443, which
 * stopped at dist1 because dist1 had no routing table. The regenerated sample collected dist1's and
 * dist2's tables, and every hop any trace of the real snapshot reaches is now on a host WITH a RIB (the
 * access switches carry none, but no trace enters at one: sources enter at their SVI gateway). So the
 * no-RIB branch no longer runs on the real data, and a guard whose success path never executes is not a
 * guard. This file asks the engine the counterfactual question "what if one gateway's routing table had
 * not been collected", with that ONE producer answered differently: the host's routes are removed from
 * the compiled model and from the coverage's routable-host list. Every other route, ACL line, binding,
 * SVI and FHRP record is the real compiled evidence, every assertion runs through the real `traceFlow`
 * and the real `HopList`, and vitest isolates modules per file, so the counterfactual never reaches
 * another test or the product. The host is chosen by PROPERTY — the first routable host (by name) that is
 * the active FHRP gateway of an observed subnet — so the file holds on any snapshot that has one.
 *
 * Moved here from PathTrace.test.tsx ("HopList — a hop on a host with no RIB", and the no-RIB case of
 * "an undecided hop on a host whose RIB WAS collected") and HopList.undecided.test.tsx ("a hop on a host
 * with NO RIB does not imply a RIB was searched"); their assertions are unchanged.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const cf = vi.hoisted(() => ({ gone: null as string | null }));

vi.mock("../core/data", async (orig) => {
  const actual = await orig<typeof import("../core/data")>();
  const f = actual.fabric;
  const candidates = f.l3
    .filter((r) => r.host !== null && f.coverage.routableHosts.includes(r.host) && /^active$/i.test(r.fhrpRole ?? ""))
    .map((r) => r.host!)
    .sort();
  const gone = candidates[0] ?? null;
  cf.gone = gone;
  if (gone === null) return actual;
  const routes = Object.fromEntries(Object.entries(f.routes).filter(([h]) => h !== gone));
  const routableHosts = f.coverage.routableHosts.filter((h) => h !== gone);
  const fabric = { ...f, routes, coverage: { ...f.coverage, routableHosts, hostsWithRoutes: routableHosts.length } };
  return {
    ...actual,
    fabric,
    hasRib: (h: string) => Object.prototype.hasOwnProperty.call(routes, h),
    routesOf: (h: string) => routes[h] ?? [],
  };
});

import { hasRib } from "../core/data";
import type { Trace } from "../core/types";
import { traceFlow } from "../forwarding/engine";
import { HopList } from "./HopList";
import { flowOf, subnetHostAddresses } from "../test-support/trace-universe";

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
  document.body.innerHTML = "";
});

const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ");

/** A host in a subnet whose ACTIVE gateway is the host without a RIB, to a host in another subnet. */
function noRibTrace(): Trace {
  expect(cf.gone, "precondition: this snapshot has a routable host that is an active FHRP gateway").not.toBeNull();
  const hosts = subnetHostAddresses();
  const src = hosts.find((h) => h.host === cf.gone && /^active$/i.test(h.fhrpRole ?? ""));
  const dst = hosts.find((h) => src !== undefined && h.vlan !== src.vlan);
  expect(src, `precondition: a host address in a subnet ${cf.gone} is the active gateway of`).toBeDefined();
  expect(dst, "precondition: a host address in another observed subnet").toBeDefined();
  return traceFlow(flowOf(src!.ip, dst!.ip, "tcp", 443));
}

describe("the counterfactual this file rests on", () => {
  it("removes exactly one gateway's RIB, and the trace stops there as not modelled", () => {
    expect(hasRib(cf.gone!), `precondition: ${cf.gone}'s RIB is counterfactually not collected`).toBe(false);
    const t = noRibTrace();
    expect(t.hops[0]?.host).toBe(cf.gone);
    expect(t.hops[0]?.verdict).toBe("unmodeled");
    expect(t.outcome).toBe("indeterminate");
    expect(t.unmodelledHosts).toContain(cf.gone);
  });
});

describe("HopList — a hop on a host with no RIB", () => {
  it("renders as UNDETERMINED with its own words, not as a pass and not as a failure", () => {
    const c = mount(<HopList trace={noRibTrace()} activeIndex={0} onSelect={() => {}} />);
    const hop = c.querySelector(".hop");
    expect(hop?.getAttribute("data-verdict")).toBe("unmodeled");
    expect(hop?.getAttribute("data-band")).toBe("UNDETERMINED");
    expect(c.querySelectorAll('.hop[data-band="RESOLVED"]').length).toBe(0);
    expect(c.querySelectorAll('.hop[data-band="REFUTED"]').length).toBe(0);
    const body = text(c);
    expect(body).toContain("not modelled");
    expect(body).toContain("no routing table was collected");
    // The absence renderer, not a blank and not a dash.
    expect(c.querySelector(".ui-notobs")).not.toBeNull();
  });

  it("does not invent an egress or a next hop it could not have observed", () => {
    const body = text(mount(<HopList trace={noRibTrace()} activeIndex={0} onSelect={() => {}} />));
    expect(body).not.toContain("delivered");
    expect(body).not.toContain("forwarded");
  });

  it("keeps the collection-gap wording for a host with NO RIB, and claims no routes were beaten there", () => {
    const c = mount(<HopList trace={noRibTrace()} activeIndex={0} onSelect={() => {}} />);
    const noRib = [...c.querySelectorAll(".hop")].find((h) => h.getAttribute("data-verdict") === "unmodeled");
    expect(noRib, "an unmodelled hop was rendered").toBeDefined();
    expect(text(noRib!)).toContain("no routing table was collected");
    expect(text(noRib!)).not.toContain("nothing was beaten");
    expect(noRib!.querySelector(".hop__why-none")).toBeNull();
  });

  it("does not imply a RIB was searched (A2)", () => {
    const c = mount(<HopList trace={noRibTrace()} activeIndex={null} onSelect={() => {}} onOpenCite={() => {}} />);
    const hop = [...c.querySelectorAll<HTMLElement>(".hop")].find((h) => h.querySelector(".hop__host")?.textContent === cf.gone);
    expect(hop, `a hop on ${cf.gone} was rendered`).toBeDefined();
    expect(hop!.textContent).not.toMatch(/collected RIB matched/);
    expect(hop!.textContent, "the no-RIB case keeps its collection-gap wording").toMatch(/no routing table was collected/);
  });
});
