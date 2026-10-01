/**
 * FabricLegend.rim.test.tsx — the operational-state key carries the SHAPE the scene draws.
 *
 * D8, 2026-09-21: the "Chassis rim — operational state" key drew Up and Down as the identical
 * solid rect, told apart only by --state-up / --state-down, while the scene distinguishes them by
 * shape (scene.ts ringShapeFor: up -> solid, down -> double, anything else -> dashed). In greyscale
 * the key did not match the fabric and Down was conveyed by colour alone (WCAG 1.4.1).
 *
 * The three swatches must be pairwise distinguishable WITHOUT colour: count of rims + dash.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { FabricLegend } from "./FabricLegend";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

/** A colour-free fingerprint of a swatch: how many rim shapes, and whether they are dashed. */
function shapeOf(row: Element): string {
  const rims = [...row.querySelectorAll(".fabric3d-legend__rim")];
  const dashed = rims.some((r) => r.getAttribute("stroke-dasharray") !== null);
  return `${rims.length}x${dashed ? "dashed" : "solid"}`;
}

describe("operational-state key", () => {
  it("draws Up solid, Down as a double ring and Unknown dashed — distinguishable in greyscale", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<FabricLegend id="lg" devices={fabric.devices} links={fabric.links} />));
    // The legend remembers whether it was open; open it if it came up collapsed.
    const show = host.querySelector<HTMLButtonElement>('[data-testid="fabric3d-legend-show"]');
    if (show) act(() => show.click());

    const group = [...host.querySelectorAll(".fabric3d-legend__group")].find((g) =>
      g.textContent?.includes("operational state"),
    );
    expect(group, "the operational-state group is missing from the legend").toBeDefined();
    const rows = [...group!.querySelectorAll(".fabric3d-legend__row")];
    const byName = (n: string): Element => {
      const r = rows.find((x) => x.querySelector(".fabric3d-legend__text")?.textContent?.startsWith(n));
      expect(r, `no "${n}" row in the operational-state key`).toBeDefined();
      return r!;
    };

    const up = shapeOf(byName("Up"));
    const down = shapeOf(byName("Down"));
    const unknown = shapeOf(byName("Unknown"));
    expect(up).toBe("1xsolid");
    expect(down, "Down must be the double ring the scene draws, not Up in another colour").toBe("2xsolid");
    expect(unknown).toBe("1xdashed");
    expect(new Set([up, down, unknown]).size).toBe(3);

    act(() => root.unmount());
  });
});
