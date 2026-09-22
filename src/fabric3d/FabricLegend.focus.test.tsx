/**
 * FabricLegend.focus.test.tsx — the Legend toggle keeps keyboard focus.
 *
 * A11Y critic, 2026-09-21 (D3): the open and closed states render DIFFERENT buttons, so the one
 * that held focus was unmounted by its own activation and focus fell to <body> in both directions
 * (zz_legend2.mjs: Space on "Legend" -> BODY; Enter on "Hide the legend" -> BODY).
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
  localStorage.clear();
});

describe("legend toggle focus", () => {
  it("moves focus into the close button on open and back to the Legend button on close", () => {
    localStorage.clear();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<FabricLegend id="lg" devices={fabric.devices} links={fabric.links} />));

    const show = host.querySelector<HTMLButtonElement>('[data-testid="fabric3d-legend-show"]');
    expect(show, "the legend should start collapsed").not.toBeNull();
    act(() => show!.focus());
    act(() => show!.click());

    const close = host.querySelector<HTMLButtonElement>(".fabric3d-legend__close");
    expect(close).not.toBeNull();
    expect(document.activeElement, "opening the legend dropped focus").toBe(close);

    act(() => close!.click());
    const again = host.querySelector<HTMLButtonElement>('[data-testid="fabric3d-legend-show"]');
    expect(document.activeElement, "closing the legend dropped focus").toBe(again);
    act(() => root.unmount());
  });

  it("does not steal focus when the toggle is driven from elsewhere (the palette)", () => {
    const host = document.createElement("div");
    const outside = document.createElement("input");
    document.body.append(host, outside);
    const root = createRoot(host);
    act(() => root.render(<FabricLegend id="lg" devices={fabric.devices} links={fabric.links} />));
    act(() => outside.focus());
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="fabric3d-legend-show"]')!.click());
    expect(document.activeElement).toBe(outside);
    act(() => root.unmount());
  });
});
