/**
 * band-qualification.surfaces.test.tsx — EVERY surface that renders a health band applies the one
 * qualification rule (independent acceptance report 2026-09-22, B1).
 *
 * THE DEFECT. A score is a sum of deductions, and a scoring domain that was never assessed on a
 * device could not deduct. So a FAVOURABLE band on a collected host whose protocols, RIB or ACLs
 * were never collected partly measures the ABSENCE of evidence. DevicePane drew that band neutral
 * and named the gap; every other surface stated it bare — the announcement read "podacc1 selected.
 * … Collected. Health band Excellent.", the Fabric list row read "podacc1 Excellent", the chassis
 * was painted the Excellent green with the letter E, and the legend counted it as "E Excellent · 2".
 *
 * The rule under test is stated HERE, independently of the owner that implements it: for a collected
 * device whose band is favourable (Excellent or Good) and whose unassessed scoring domains
 * (`unassessedScoringDomains`, read from the per-host coverage records) are non-empty, no surface
 * may render that band as a plain favourable band. The enumeration below is every surface that
 * renders a band on the fabric side of the product, plus the Device pane that owned the rule first.
 * A new band surface belongs in SURFACES; the test fails loudly if the qualified set is empty, so
 * it cannot pass over nothing.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Color } from "three";
import { afterEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Device } from "../core/types";
import { DevicePane, unassessedScoringDomains } from "../panels/DevicePane";
import { PriorityQueue } from "../panels/PriorityQueue";
import { CommandPalette } from "../app/CommandPalette";
import { suggest } from "../core/query";

import type { FabricScene } from "./contract";
import { describeDevice } from "./Fabric3D";
import { FabricA11yTree } from "./FabricA11yTree";
import { createHoverChannel, FabricLabels } from "./FabricLabels";
import { FabricLegend } from "./FabricLegend";
import { computeLayout } from "./layout";
import { profileFor } from "./quality";
import { buildFabricGraph } from "./scene";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const FAVOURABLE = new Set(["Excellent", "Good"]);

/** The rule, restated by the test: favourable band + collected + at least one unassessed domain. */
const gapsOf = (d: Device): string[] => (d.collected ? unassessedScoringDomains(d.host) : []);
const isQualified = (d: Device): boolean => d.band !== null && FAVOURABLE.has(d.band) && gapsOf(d).length > 0;
/** "protocol health (not assessed)" -> "protocol health": the domain's name without its reason. */
const domainName = (g: string): string => g.replace(/\s*\(.*$/, "");

const QUALIFIED = fabric.devices.filter(isQualified);

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: React.ReactNode): HTMLElement {
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
  act(() => useInvestigation.getState().reset());
});

/** Every gap must be NAMED where the band is stated in words. */
function expectNamesEveryGap(text: string, d: Device, surface: string): void {
  for (const g of gapsOf(d)) expect(text, `${surface}: ${d.host} does not name "${domainName(g)}"`).toContain(domainName(g));
}

interface Surface {
  name: string;
  check(devices: readonly Device[]): void;
}

const SURFACES: Surface[] = [
  {
    name: "Device pane (score row)",
    check(devices) {
      const c = mount(<DevicePane />);
      for (const d of devices) {
        act(() => useInvestigation.getState().selectDevice(d.host));
        const band = c.querySelector<HTMLElement>(".ui-band");
        expect(band?.className, d.host).toContain("dp-band--partial");
        expectNamesEveryGap(c.querySelector(".dp-score-gap")?.textContent ?? "", d, "Device pane");
      }
    },
  },
  {
    name: "canvas live-region announcement (describeDevice)",
    check(devices) {
      for (const d of devices) {
        const s = describeDevice(d.id);
        expect(s, d.host).not.toContain(`Health band ${d.band}.`);
        expectNamesEveryGap(s, d, "announcement");
      }
    },
  },
  {
    name: "Fabric list (a11y tree) device row",
    check(devices) {
      const c = mount(
        <FabricA11yTree
          devices={fabric.devices}
          links={fabric.links}
          tiers={[fabric.devices.map((d) => d.host)]}
          visible
          onHide={() => {}}
          onFocusDevice={() => {}}
        />,
      );
      for (const d of devices) {
        const row = c.querySelector<HTMLElement>(`[data-testid="fabric3d-tree-device"][data-target="${d.id}"]`);
        expect(row, d.host).not.toBeNull();
        const meta = row!.querySelector(".fabric3d__tree-meta")?.textContent ?? "";
        expect(meta, d.host).not.toBe(d.band);
        expectNamesEveryGap(meta, d, "tree row");
      }
    },
  },
  {
    name: "on-canvas label band chip (letter)",
    check(devices) {
      const scene = { project: () => null } as unknown as FabricScene;
      const c = mount(
        <FabricLabels devices={fabric.devices} sceneRef={{ current: scene }} epoch={0} hover={createHoverChannel()} selectedId={null} />,
      );
      for (const d of devices) {
        const chip = c.querySelector<HTMLElement>(`.fabric3d-label[data-device="${d.id}"] .fabric3d-label__band`);
        expect(chip, d.host).not.toBeNull();
        // The bare favourable letter is exactly the unqualified rendering.
        expect(chip!.textContent, d.host).not.toBe(d.band!.slice(0, 1));
        // Its machine-readable band is the qualified key too, not the bare favourable band.
        expect(chip!.getAttribute("data-band"), d.host).not.toBe(d.band);
        expectNamesEveryGap(chip!.getAttribute("title") ?? "", d, "label chip title");
      }
    },
  },
  {
    name: "legend band counts",
    check(devices) {
      // The legend is closed by default; its own stored preference opens it.
      window.localStorage.setItem("atlas-scope.fabric-legend.open", "1");
      const c = mount(<FabricLegend id="lg" devices={fabric.devices} links={fabric.links} />);
      const rows = [...c.querySelectorAll<HTMLElement>(".fabric3d-legend__row")];
      const countOf = (name: string): number | null => {
        const row = rows.find((r) => (r.querySelector(".fabric3d-legend__text")?.firstChild?.textContent ?? "").trim() === name);
        const n = row?.querySelector(".fabric3d-legend__count")?.textContent;
        return n === undefined || n === null ? null : Number(n);
      };
      for (const band of FAVOURABLE) {
        const plain = fabric.devices.filter((d) => d.band === band && !isQualified(d)).length;
        expect(countOf(band), `legend "${band}" counts only devices whose band is not qualified`).toBe(plain);
      }
      // The qualified devices are counted somewhere, not dropped: every device is in exactly one band row.
      const bandRows = rows.filter((r) => r.closest(".fabric3d-legend__group")?.querySelector("h3")?.textContent?.includes("health band"));
      const total = bandRows.reduce((n, r) => n + Number(r.querySelector(".fabric3d-legend__count")?.textContent ?? 0), 0);
      expect(total, "every device is counted in exactly one band row").toBe(fabric.devices.length);
      expect(devices.length).toBeGreaterThan(0);
    },
  },
  {
    name: "command palette device row",
    check(devices) {
      mount(<CommandPalette />);
      act(() => useInvestigation.getState().setPaletteOpen(true));
      const input = document.querySelector<HTMLInputElement>(".palette__input");
      expect(input).not.toBeNull();
      for (const d of devices) {
        act(() => {
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, d.host);
          input!.dispatchEvent(new Event("input", { bubbles: true }));
        });
        const row = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
          (o) => o.querySelector(".ui-band") !== null && (o.textContent ?? "").includes(d.host),
        );
        expect(row, `${d.host}: no palette row with a band`).toBeDefined();
        const pill = row!.querySelector<HTMLElement>(".ui-band")!;
        // The bare favourable word is exactly the unqualified rendering.
        expect(pill.textContent?.trim(), d.host).not.toBe(d.band);
        expect(pill.textContent, d.host).toContain("partial");
        expectNamesEveryGap(pill.getAttribute("title") ?? "", d, "palette band pill title");
      }
      act(() => useInvestigation.getState().setPaletteOpen(false));
    },
  },
  {
    name: "query host: row description (palette/filter vocabulary)",
    check(devices) {
      for (const d of devices) {
        const row = suggest(`host:${d.host}`, `host:${d.host}`.length).suggestions.find((s) => s.value === d.host);
        expect(row, d.host).toBeDefined();
        expect(row!.detail ?? "", d.host).toContain("partial");
        expectNamesEveryGap(row!.detail ?? "", d, "host: row description");
      }
    },
  },
  {
    name: "priority queue grouped by device health band",
    check(devices) {
      const c = mount(<PriorityQueue debounceMs={0} />);
      const select = [...c.querySelectorAll<HTMLSelectElement>("select")].find((s) =>
        [...s.options].some((o) => o.value === "band"),
      );
      expect(select, "the queue offers no band grouping").toBeDefined();
      act(() => {
        select!.value = "band";
        select!.dispatchEvent(new Event("change", { bubbles: true }));
      });
      const labels = [...c.querySelectorAll<HTMLElement>(".ag__row--group .ag__grouplabel")].map((l) => (l.textContent ?? "").trim());
      expect(labels.length).toBeGreaterThan(0);
      for (const band of new Set(devices.map((d) => d.band!))) {
        // A plain bucket for this band may only exist if some device carries it UNqualified.
        const plainCarriers = fabric.devices.filter((x) => x.band === band && !isQualified(x)).length;
        if (plainCarriers === 0) expect(labels, `queue groups qualified "${band}" findings as plain "${band}"`).not.toContain(band);
        expect(labels.some((l) => l.startsWith(`${band} (partial)`)), `no qualified "${band}" bucket in ${labels.join(" | ")}`).toBe(true);
      }
    },
  },
  {
    name: "3-D chassis body tint and status LED",
    check(devices) {
      const layout = computeLayout({ devices: fabric.devices, links: fabric.links, tiers: fabric.tiers });
      const graph = buildFabricGraph({ devices: fabric.devices, links: fabric.links, layout, theme: "dark", profile: profileFor("high") });
      const c = new Color();
      for (const d of devices) {
        const s = graph.slots.get(d.id);
        expect(s, d.host).toBeDefined();
        for (const [part, mesh] of [["body", s!.group.body], ["led", s!.group.led]] as const) {
          if (mesh === null) continue;
          mesh.getColorAt(s!.slot, c);
          // A favourable band's hue on the chassis IS the unqualified rendering; the qualified
          // presentation is neutral (achromatic), the same neutral the Device pane draws.
          const chroma = Math.max(c.r, c.g, c.b) - Math.min(c.r, c.g, c.b);
          expect(chroma, `${d.host} ${part} carries the ${d.band} hue`).toBeLessThan(1e-3);
        }
      }
    },
  },
];

describe("a favourable band on a host with unassessed scoring domains is qualified on EVERY surface (B1)", () => {
  it("the snapshot holds such hosts, and podacc1 — the audited one — is among them", () => {
    expect(QUALIFIED.length).toBeGreaterThan(0);
    expect(QUALIFIED.map((d) => d.host)).toContain("podacc1");
  });

  for (const surface of SURFACES) {
    it(
      surface.name,
      () => {
        expect(QUALIFIED.length, "no qualified host to check this surface against").toBeGreaterThan(0);
        surface.check(QUALIFIED);
      },
      60_000,
    );
  }
});
