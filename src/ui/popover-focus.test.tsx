/**
 * popover-focus.test.tsx — a non-modal Popover closes when focus leaves it, and Escape reaches it
 * even when the element under focus handles Escape itself.
 *
 * A11Y critic, 2026-09-21 (D3), zz_d3pop2.mjs: open "Why the two tables are counted separately",
 * Tab to the "Filter findings" input, Escape -> focus stays on the input and the dialog stays open
 * over the content. Two causes: nothing closed the popover when focus left it, and its Escape
 * listener sat in the bubble phase, where the input's own Escape handler stopped the event first.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { IconInfo } from "./icons";
import { Copyable, IconButton, Popover } from "./primitives";

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

/* ══ the control a popover opens onto must be SEEN (D3, visibility) ══════════════════════════════
   MEASURED 2026-09-23 (independent acceptance review, then review/audit-d3-focus.mjs at 1440 and
   1920): the snapshot popover opens with focus on "Copy the snapshot sha256", and that button sat
   at x=641–668 while the popover ended at x=554 — `elementFromPoint` at its centre was the 3-D
   canvas. The cause was the PRIMITIVE, not the header: `.ui-copyable` is an inline flex box, and an
   inline box sizes to its content's min-content width, which for a no-wrap 64-digit sha is the whole
   sha. The dd around it has `min-width: 0`; nothing bounded the Copyable itself, so it overflowed
   the dd, the row, and the popover's scroll box, and took its button with it.
   jsdom lays nothing out, so these pin the contract; the pixels are the audit's. */

const primitivesCss = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "primitives.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  " ",
);

/** The declarations of every unconditional rule whose selector list contains exactly `selector`. */
function declarations(selector: string): Map<string, string> {
  const out = new Map<string, string>();
  const re = /(@[^{;]*)\{|([^{}]+)\{([^{}]*)\}|\}/g;
  let depth = 0;
  for (let m = re.exec(primitivesCss); m !== null; m = re.exec(primitivesCss)) {
    if (m[1] !== undefined) depth += 1;
    else if (m[2] !== undefined) {
      if (depth > 0 || !m[2].split(",").some((s) => s.trim() === selector)) continue;
      for (const d of (m[3] ?? "").matchAll(/([\w-]+)\s*:\s*([^;]+)/g)) out.set(d[1]!, d[2]!.trim());
    } else depth = Math.max(0, depth - 1);
  }
  return out;
}

const SHA = "9580aa092d490a13ba420b2cc670ddee026f6dbf93ecc5aeac2a9a9fb2be3089";

describe("a Copyable's button cannot be pushed outside the box it sits in", () => {
  it("bounds the Copyable to its container, whatever the length of its value", () => {
    const box = declarations(".ui-copyable");
    const max = box.get("max-inline-size") ?? box.get("max-width");
    expect(max, ".ui-copyable declares no inline-size bound; a long value pushes its button out of the container").toBe("100%");
    /* The value is the part that gives way: it may shrink below its content, the button may not. */
    const value = declarations(".ui-copyable__value");
    expect(value.get("min-inline-size") ?? value.get("min-width")).toBe("0");
  });

  it("wraps a digest inside its box, rather than cutting it or overflowing it", () => {
    const host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    act(() => root!.render(<Copyable value={SHA} label="the snapshot sha256" digest />));
    const value = host.querySelector(".ui-copyable__value");
    expect(host.querySelector(".ui-copyable")?.classList.contains("ui-copyable--digest")).toBe(true);
    expect(value?.textContent, "the digest is shown whole, never elided").toBe(SHA);
    /* A sha256 has no `_ . / -` boundary: the one licensed break is the UNBREAKABLE-TOKEN CONTAINER
       (see "wrapping" in primitives.css), and an ellipsis there would hide ~30% of the digest. */
    const digest = declarations(".ui-copyable--digest .ui-copyable__value");
    expect(digest.get("overflow-wrap")).toBe("anywhere");
    expect(digest.get("white-space")).toBe("normal");
  });

  it("the popover still opens onto the Copyable's button, which is inside the panel", () => {
    const host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    act(() =>
      root!.render(
        <Popover label="Provenance" trigger={<IconButton size="sm" label="Open" icon={<IconInfo />} />}>
          <Copyable value={SHA} label="the snapshot sha256" digest />
        </Popover>,
      ),
    );
    const trigger = host.querySelector("button")!;
    act(() => trigger.focus());
    act(() => trigger.click());
    const panel = document.querySelector('[role="dialog"]');
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Copy the snapshot sha256");
    expect(panel?.contains(document.activeElement)).toBe(true);
    expect(document.activeElement?.closest(".ui-copyable")).not.toBeNull();
  });
});
