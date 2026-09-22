/**
 * popover-focus.test.tsx — a non-modal Popover closes when focus leaves it, and Escape reaches it
 * even when the element under focus handles Escape itself.
 *
 * A11Y critic, 2026-09-21 (D3), zz_d3pop2.mjs: open "Why the two tables are counted separately",
 * Tab to the "Filter findings" input, Escape -> focus stays on the input and the dialog stays open
 * over the content. Two causes: nothing closed the popover when focus left it, and its Escape
 * listener sat in the bubble phase, where the input's own Escape handler stopped the event first.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { IconInfo } from "./icons";
import { IconButton, Popover } from "./primitives";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  document.body.innerHTML = "";
});

function setup(): { trigger: HTMLButtonElement; outside: HTMLInputElement } {
  const host = document.createElement("div");
  const outside = document.createElement("input");
  /* The shape of the query input / grid: it handles Escape and stops propagation. */
  outside.addEventListener("keydown", (e) => {
    if (e.key === "Escape") e.stopPropagation();
  });
  document.body.append(host, outside);
  root = createRoot(host);
  act(() =>
    root!.render(
      <Popover label="Why" trigger={<IconButton size="sm" label="Why" icon={<IconInfo />} />}>
        <p>reason</p>
      </Popover>,
    ),
  );
  return { trigger: host.querySelector("button")!, outside };
}

const dialogs = (): number => document.querySelectorAll('[role="dialog"]').length;

describe("Popover focus and Escape", () => {
  it("closes when focus moves outside the trigger and the panel", () => {
    const { trigger, outside } = setup();
    act(() => trigger.focus());
    act(() => trigger.click());
    expect(dialogs()).toBe(1);
    act(() => outside.focus());
    expect(dialogs(), "the popover stayed open after focus left it").toBe(0);
    expect(document.activeElement, "closing on focus-out must not pull focus back").toBe(outside);
  });

  it("closes on Escape even when the focused element stops Escape from bubbling", () => {
    const { trigger } = setup();
    act(() => trigger.focus());
    act(() => trigger.click());
    expect(dialogs()).toBe(1);
    /* A descendant handler that stops propagation: dispatched on the trigger's own child. */
    const stopper = document.createElement("span");
    trigger.appendChild(stopper);
    stopper.addEventListener("keydown", (e) => e.stopPropagation());
    act(() => {
      stopper.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(dialogs()).toBe(0);
    expect(document.activeElement).toBe(trigger);
  });
});
