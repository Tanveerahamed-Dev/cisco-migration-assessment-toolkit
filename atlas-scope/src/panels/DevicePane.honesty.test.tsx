/**
 * DevicePane.honesty.test.tsx — a count or a grade on the device pane means what it says.
 *
 * 2026-09-21 critic findings (B1):
 *  - the Routing tab's badge counted L3 SVIs, not RIB entries (core1 read "3" over an 8-entry RIB);
 *  - a port the producer marks "L1 error rate NOT assessed" still wore the producer's "Info" chip,
 *    the same chip an assessed clean port earns.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric, physicalByHost, routesOf } from "../core/data";
import { useInvestigation } from "../core/store";
import { DevicePane, unassessedScoringDomains } from "./DevicePane";
import { ribCountQualifier, ribHostsShownIncomplete, ribIncompleteness } from "../forwarding/rib-completeness";
import { coverageRows } from "../app/CoverageBar";
import { describeGolden } from "../test-support/golden-sample";
import { need, nonEmpty } from "../test-support/trace-universe";

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

/* RE-EXPRESSED 2026-09-28 (phase 3): the hosts are the snapshot's routable hosts, read from its coverage,
   not the two names the old sample happened to collect RIBs for. */
describe("the Routing tab badge is the RIB size", () => {
  for (const host of fabric.coverage.routableHosts) {
    it(host, () => {
      const n = routesOf(host).length;
      expect(n, "precondition: a RIB was collected").toBeGreaterThan(0);
      act(() => { useInvestigation.getState().selectDevice(host); });
      const c = mount(<DevicePane />);
      const tab = [...c.querySelectorAll<HTMLElement>('[role="tab"]')].find((t) => /Routing/.test(t.textContent ?? ""));
      // The badge is the RIB size; a table the snapshot shows incomplete says so beside it (B7).
      const partial = ribIncompleteness(host).length > 0;
      expect(tab?.textContent).toBe(`Routing${partial ? "incomplete" : ""}${n}`);
    });
  }
});

describe("a collected routing table the snapshot shows incomplete is never presented as whole (B7, 2026-09-22)", () => {
  /* RE-EXPRESSED 2026-09-28 (phase 3). This iterated core1 and core2 and required both tables to be shown
     incomplete; the regenerated sample completed core1's (and collected dist1's and dist2's), so only
     core2's is still partial. The subjects are now read from the owner — every host the snapshot shows
     incomplete — and the counterpart is pinned too: a COMPLETE collected table is not described as
     incomplete. */
  const tabText = (host: string): string => {
    act(() => {
      useInvestigation.getState().selectDevice(host);
      useInvestigation.getState().setEvidenceTab("routing");
    });
    const c = mount(<DevicePane />);
    return c.textContent ?? "";
  };

  it("the snapshot shows some collected table incomplete", (ctx) => {
    expect(need(ctx, nonEmpty(ribHostsShownIncomplete()), "collected routing table shown incomplete").length).toBeGreaterThan(0);
  });

  for (const host of ribHostsShownIncomplete()) {
    it(`${host}: shown incomplete, with every reason`, () => {
      const reasons = ribIncompleteness(host);
      expect(reasons.length, "precondition: the snapshot shows this table incomplete").toBeGreaterThan(0);
      const text = tabText(host);
      expect(text).not.toMatch(/on those entries and on nothing else/);
      expect(text).toMatch(/shows that table to be incomplete/);
      for (const r of reasons) expect(text).toContain(r.label);
    });
  }

  it("a complete collected table is not described as incomplete", (ctx) => {
    const complete = need(ctx, fabric.coverage.routableHosts.find((h) => ribIncompleteness(h).length === 0), "complete collected routing table");
    expect(tabText(complete)).not.toMatch(/shows that table to be incomplete/);
  });

  it("the RIB count carries the qualifier wherever it is shown, with counts read from the data", () => {
    const all = fabric.coverage.routableHosts.length;
    const partial = ribHostsShownIncomplete().length;
    const q = ribCountQualifier();
    expect(q === "", "a qualifier exactly when some table is shown incomplete").toBe(partial === 0);
    if (partial > 0 && partial < all) expect(q).toContain(`${partial} of ${all}`);
    if (partial > 0) expect(coverageRows().some((r) => r.meaning.includes(q)), "the coverage bar's RIB row carries it").toBe(true);
  });

  describeGolden("the reference sample's qualifier", () => {
    it("one of four collected tables is shown incomplete", () => {
      expect(ribCountQualifier()).toBe("(1 of 4 shown incomplete)");
    });
  });
});

describe("an unassessed port is not graded", () => {
  it("every row with the producer's NOT-assessed marker renders 'not graded', never a severity chip", () => {
    /* The device is found by property — the first (by name) carrying unassessed rows; the auditor's was
       access1 (phase 3 rename leg). */
    type Phys = { port: string; risk: string | null; riskUnobserved?: string | null; severity: string | null };
    const unassessedOf = (h: string): Phys[] =>
      ((physicalByHost.get(h) ?? []) as unknown as Phys[]).filter((r) => r.risk === null && typeof r.riskUnobserved === "string");
    const host = [...physicalByHost.keys()].sort().find((h) => unassessedOf(h).length > 0);
    expect(host, "precondition: some device carries unassessed rows").toBeDefined();
    const unassessed = unassessedOf(host!);
    const device = fabric.devices.find((d) => d.host === host);
    expect(device, "precondition: the device is in the inventory").toBeDefined();
    act(() => {
      useInvestigation.getState().selectDevice(device!.id);
      useInvestigation.getState().setEvidenceTab("ports");
    });
    const c = mount(<DevicePane />);
    const grid = c.querySelector<HTMLElement>("#dp-panel-ports")!;
    expect(grid.querySelectorAll("[data-ungraded]").length).toBe(unassessed.length);
    for (const u of grid.querySelectorAll("[data-ungraded]")) {
      expect(u.textContent).toMatch(/not graded/);
      expect(u.closest('[role="row"]')?.textContent).not.toMatch(/Info severity/);
    }
  });
});

describe("a favourable health band names the scoring domains that were never assessed (2026-09-22 auditor, B1)", () => {
  /* podacc1 read "90 Excellent" in the healthy tone beside "Its routing and switching protocols were
     not assessed here", with no RIB and no ACL collected: a domain never assessed cannot deduct, so
     the band partly measured absence. The sweep runs over EVERY device the snapshot scores. */
  it("every scored, collected device either has every domain assessed or names the gaps beside its band", () => {
    let qualified = 0;
    let checked = 0;
    // One mounted pane, re-aimed per device: 23 separate mounts timed out under the full parallel suite.
    const c = mount(<DevicePane />);
    for (const d of fabric.devices) {
      if (!d.collected || !d.band) continue;
      const gaps = unassessedScoringDomains(d.host);
      act(() => { useInvestigation.getState().selectDevice(d.host); });
      const band = c.querySelector<HTMLElement>(".ui-band");
      expect(band, d.host).toBeTruthy();
      const note = c.querySelector(".dp-score-gap");
      checked += 1;
      if (gaps.length === 0) {
        expect(note, d.host).toBeNull();
        continue;
      }
      expect(note?.textContent, d.host).toContain("score does not reflect");
      for (const g of gaps) expect(note?.textContent, d.host).toContain(g);
      if (d.band === "Excellent" || d.band === "Good") {
        qualified += 1;
        expect(band!.className, d.host).toContain("dp-band--partial");
        expect(c.querySelector(".ui-meter")?.getAttribute("data-tone"), d.host).toBe("neutral");
      }
    }
    expect(checked).toBeGreaterThan(0);
    expect(qualified, "no favourable band on an under-assessed device was checked").toBeGreaterThan(0);
  }, 60_000);

  describeGolden("the auditor's device", () => {
    it("podacc1 — the auditor's device — names protocol health, routing and ACLs", () => {
      expect(unassessedScoringDomains("podacc1")).toEqual(
        expect.arrayContaining(["protocol health (not assessed)", "routing (no RIB collected)", "ACLs (none collected)"]),
      );
    });
  });
});
