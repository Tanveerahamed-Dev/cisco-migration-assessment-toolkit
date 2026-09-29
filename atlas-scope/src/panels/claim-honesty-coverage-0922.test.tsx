/**
 * claim-honesty-coverage-0922.test.tsx — the 2026-09-22 claim-honesty / coverage audit findings.
 *
 *  - B1: a cable with one never-collected end printed "7 findings across 2 hosts" over a tally whose
 *        second half was silence (a `some(collected)` guard standing in for `every`).
 *  - B1: an observed NEGATIVE ("not in a channel group" in a collected configuration) wore the
 *        not-observed marker.
 *  - B7: the coverage "Inventory record" row said "a model, serial and software record exists" over
 *        a flag that only says a record was returned; core2 has no software version.
 *  - B2: a delivery on a connected route at a host whose table is shown incomplete carried no word
 *        about the partial table (longest-prefix match lets a longer route outrank a connected /24).
 *
 * Every precondition is read from the compiled fabric, not typed in.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { coverageRows } from "../app/CoverageBar";
import { missingInventoryFields } from "../core/claims";
import { deviceById, fabric, routesOf } from "../core/data";
import type { Trace } from "../core/types";
import { describeGolden } from "../test-support/golden-sample";
import { need, universeTraces } from "./trace-universe";
import { useInvestigation } from "../core/store";
import { traceFlow } from "../forwarding/engine";
import { ribIncompletenessSentence } from "../forwarding/rib-completeness";
import { DevicePane } from "./DevicePane";

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
beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setEvidenceTab("summary");
  });
});
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

const openTab = (c: HTMLElement, name: RegExp): void => {
  const tab = [...c.querySelectorAll<HTMLElement>('[role="tab"]')].find((t) => name.test(t.textContent ?? ""));
  expect(tab, `tab ${name}`).toBeDefined();
  act(() => tab!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
};

describe("a cable's Findings tab splits a mixed collection scope (B1)", () => {
  const collected = (h: string): boolean => deviceById.get(h)?.collected === true;
  const mixed = fabric.links.filter((l) => collected(l.a) !== collected(l.b));

  it("every mixed cable names its never-collected end and never tallies 'across 2 hosts'", () => {
    expect(mixed.length, "precondition: some cable has exactly one collected end").toBeGreaterThan(0);
    for (const link of mixed) {
      act(() => { useInvestigation.getState().selectLink(link.id); });
      const c = mount(<DevicePane />);
      openTab(c, /^Findings/);
      const text = c.textContent ?? "";
      const missing = collected(link.a) ? link.b : link.a;
      expect(text, link.id).toContain(`${missing} was never collected`);
      expect(text, link.id).not.toMatch(/across 2 hosts/);
      act(() => mounted.pop()!.root.unmount());
    }
  });
});

describe("an observed negative is not rendered as not observed (B1)", () => {
  it("a port with a collected configuration and no channel group reads 'none', not 'not observed'", () => {
    const hit = Object.entries(fabric.interfaces)
      .flatMap(([host, list]) => list.map((i) => ({ host, i })))
      .find(({ host, i }) => i.runConfigObserved === true && !i.portChannel && deviceById.get(host)?.collected);
    expect(hit, "precondition").toBeDefined();
    act(() => { useInvestigation.getState().selectDevice(hit!.host); });
    const c = mount(<DevicePane />);
    openTab(c, /^Ports/);
    const text = c.textContent ?? "";
    expect(text).toContain("none — not in a channel group");
    expect(text).not.toMatch(/port-channel membership: not observed[^]*?this port is not in a channel group/);
  });
});

describe("the inventory coverage rows count record CONTENT separately from the flag (B7)", () => {
  it("a device whose record lacks a software version is not counted as having one", () => {
    const incomplete = fabric.devices.filter((d) => d.inventoried && missingInventoryFields(d).length > 0);
    expect(incomplete.length, "precondition: some inventoried device lacks a field").toBeGreaterThan(0);
    const rows = coverageRows();
    const flag = rows.find((r) => r.id === "inventory")!;
    const content = rows.find((r) => r.id === "inventory-fields")!;
    expect(flag.meaning).not.toMatch(/model, serial and software record exists/);
    expect(content.observed).toBe(flag.observed - incomplete.length);
    expect(content.observed + content.absent + content.notApplicable).toBe(content.total);
  });
});

describe("a connected delivery on an incomplete table names the partial table (B2)", () => {
  /* RE-EXPRESSED 2026-09-28 (phase 3). This named tcp 10.0.10.50 -> 10.0.30.10:443, delivered on a
     connected route at core1, whose table the old sample showed incomplete. The regenerated sample
     completed core1's table, so the property moved: the subject is now found by property — a delivery on
     a connected route at a host whose table the snapshot shows incomplete. */
  const subject = (): Trace | undefined =>
    universeTraces().find((t) => {
      const last = t.hops[t.hops.length - 1];
      if (t.outcome !== "delivered" || last === undefined || ribIncompletenessSentence(last.host) === null) return false;
      const cite = last.evidence.find((e) => e.kind === "route")?.cite;
      return routesOf(last.host).find((r) => r.cite === cite)?.source === "connected";
    });

  it("a connected delivery at a host whose table is shown incomplete discloses the partial RIB in a longest-prefix caveat", (ctx) => {
    const t = need(ctx, subject(), "connected delivery at a host whose table is shown incomplete");
    const sentence = ribIncompletenessSentence(t.hops[t.hops.length - 1]!.host)!;
    expect(t.caveats.some((c) => c.includes(sentence) && /longest-prefix/.test(c))).toBe(true);
  });

  describeGolden("the reference sample's case", () => {
    it("core2 delivering 10.0.20.50 -> 10.0.10.50 on its connected Vlan10", () => {
      const t = traceFlow({ srcIp: "10.0.20.50", dstIp: "10.0.10.50", protocol: "tcp", dstPort: 443, srcPort: null });
      const last = t.hops[t.hops.length - 1]!;
      expect(last.host).toBe("core2");
      expect(last.outIntf).toBe("Vlan10");
      const sentence = ribIncompletenessSentence(last.host);
      expect(sentence, "precondition: the delivering host's table is shown incomplete").not.toBeNull();
      expect(t.caveats.some((c) => c.includes(sentence!) && /longest-prefix/.test(c))).toBe(true);
    });
  });
});
