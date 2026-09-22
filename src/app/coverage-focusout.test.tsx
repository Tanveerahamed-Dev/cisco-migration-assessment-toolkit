/**
 * coverage-focusout.test.tsx — the status bar's coverage disclosure never hides a focus target.
 *
 * WCAG 2.4.11 (Focus Not Obscured, AA). The disclosure is a large, non-modal panel that overlays
 * the fabric legend and Rail B's queue. An audit found that after opening it from "23/26
 * collected" or "claim strength" and pressing Tab, keyboard focus walked onto controls the panel
 * fully covered, because it only closed on Escape and outside mousedown. The property pinned here
 * is the structural one: focus arriving ANYWHERE outside the panel and its own bar dismisses it.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { StatusBar } from "./StatusBar";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLElement | null = null;

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

function mount(): { outside: HTMLButtonElement } {
  host = document.createElement("div");
  const outside = document.createElement("button");
  outside.textContent = "Legend";
  document.body.append(host, outside);
  root = createRoot(host);
  act(() => root!.render(<StatusBar />));
  return { outside };
}

const panel = (): Element | null => document.querySelector(".covpanel");

describe("coverage disclosure focus-out", () => {
  for (const trigger of ["collected", "claim strength"]) {
    it(`closes when focus leaves it (opened from "${trigger}")`, () => {
      const { outside } = mount();
      const btn = [...host!.querySelectorAll("button")].find((b) => b.textContent?.includes(trigger));
      expect(btn).toBeDefined();
      act(() => btn!.click());
      expect(panel()).not.toBeNull();

      // Focus moving within the panel keeps it open.
      const inner = panel()!.querySelector("button")!;
      act(() => inner.focus());
      expect(panel()).not.toBeNull();

      // Focus moving to a control the panel could cover dismisses it, and stays where it went.
      act(() => outside.focus());
      expect(panel()).toBeNull();
      expect(document.activeElement).toBe(outside);
    });
  }

  it("stays open while focus moves among the status bar's own triggers", () => {
    mount();
    const buttons = [...host!.querySelectorAll("button")];
    const collected = buttons.find((b) => b.textContent?.includes("collected"))!;
    act(() => collected.click());
    const rib = buttons.find((b) => b.textContent?.includes("RIBs"))!;
    act(() => rib.focus());
    expect(panel()).not.toBeNull();
  });
});
