/**
 * rung-focus-queue-fold.test.tsx — acceptance D3, class D3-R2-1, the one member of the class whose
 * layout is decided by MEASUREMENT rather than by the viewport ladder: the queue's View disclosure.
 *
 * MEASURED on a release build (independent verifier, D3-R2-1): 'LOST 1100->1440 stop 13: BUTTON.ui-btn
 * "View" -> BODY'. The queue folds its Group/Order/Display block under "View" when the block would
 * crowd the rows out, and unfolds it when there is room again — and unfolding REMOVES the View button.
 * The old hand-off was a microtask queued from the ResizeObserver callback, which ran before React
 * committed the unfold (focus was still on the button, so it did nothing) and the commit then took the
 * button away.
 *
 * rung-focus-crossing.test.tsx proves the frame's layout door on the rung crossings, and App's door
 * (keyed on the rung) also happens to cover a fold that coincides with one. This file mounts the queue
 * ON ITS OWN, with no frame around it, so the only door that can act is the queue's own
 * (`useReleaseFocusOnLayoutChange(viewFolded)`, PriorityQueue.tsx): a fold decided by measurement
 * without any rung crossing — a splitter drag, a trace opening the path panel — must hand focus on
 * too. The room is changed with a `resize` event, which is one of the queue's own re-measure triggers.
 *
 * jsdom has no layout, so it is supplied the way PriorityQueue.a4-scroll.test.tsx supplies it: a port,
 * a sticky header, rows positioned from their index — plus the Group/Order/Display block, which takes
 * CONTROLS_PX off the top of the port while it is shown (that is what folding it buys).
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useInvestigation } from "../core/store";
import { PriorityQueue } from "../panels/PriorityQueue";
import { flushTurns } from "../test-support/act-turns";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const HEAD_PX = 40;
const ROW_PX = 47;
const CONTROLS_PX = 100;
/** Too little room with the block shown (4 rows), enough with it folded (6): the queue folds. */
const TIGHT_BOTTOM = 330;
/** Room for the block and far more than the six-row floor: the queue unfolds. */
const ROOMY_BOTTOM = 1000;

let portBottom = TIGHT_BOTTOM;
let width = 400;
const mounted: { root: Root; container: HTMLElement }[] = [];
const restores: (() => void)[] = [];

const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: width, width, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(ui);
  });
  mounted.push({ root, container });
  return container;
}

function installLayout(): void {
  const controlsShown = (from: Element): boolean => {
    const c = from.closest(".pq")?.querySelector<HTMLElement>(".pq-controls") ?? document.querySelector<HTMLElement>(".pq-controls");
    return c !== null && !c.hidden;
  };
  const originalRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.classList.contains("pq-controls")) return this.hidden ? rect(0, 0) : rect(0, CONTROLS_PX);
    if (this.classList.contains("ag__grid")) return rect(controlsShown(this) ? CONTROLS_PX : 0, portBottom);
    if (this.classList.contains("ag__row--head")) {
      const top = controlsShown(this) ? CONTROLS_PX : 0;
      return rect(top, top + HEAD_PX);
    }
    if (this.classList.contains("ag__row--data")) {
      const owner = this.closest<HTMLElement>(".ag__grid");
      const rows = owner ? [...owner.querySelectorAll<HTMLElement>(".ag__row--data")] : [];
      const top = (controlsShown(this) ? CONTROLS_PX : 0) + HEAD_PX + rows.indexOf(this) * ROW_PX;
      return rect(top, top + ROW_PX);
    }
    return originalRect.call(this) as DOMRect;
  };
  restores.push(() => {
    HTMLElement.prototype.getBoundingClientRect = originalRect;
  });
  /* The queue re-decides per GEOMETRY (its width and every clipping ancestor's box): a new width is a
     new geometry, as a real resize is. No ancestor clips in a document with no stylesheet. */
  const originalWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => width });
  const originalStyle = window.getComputedStyle;
  window.getComputedStyle = ((el: Element, pseudo?: string | null) => {
    const s = originalStyle.call(window, el, pseudo);
    return new Proxy(s, { get: (t, k) => (k === "overflowY" ? "visible" : Reflect.get(t, k, t)) });
  }) as typeof window.getComputedStyle;
  restores.push(() => {
    window.getComputedStyle = originalStyle;
    if (originalWidth !== undefined) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalWidth);
  });
}

const settle = (): Promise<void> => flushTurns(20, 8);
const where = (): string => {
  const a = document.activeElement;
  if (a === null || a === document.body) return "BODY";
  return `${a.tagName}.${(a as HTMLElement).className} "${(a.getAttribute("aria-label") ?? a.textContent ?? "").trim().slice(0, 40)}"`;
};

beforeEach(() => {
  portBottom = TIGHT_BOTTOM;
  width = 400;
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  try {
    localStorage.clear();
  } catch {
    /* preferences are not evidence */
  }
  act(() => {
    useInvestigation.getState().reset();
  });
  installLayout();
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => {
      m.root.unmount();
    });
    m.container.remove();
  }
  for (const r of restores.splice(0).reverse()) r();
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  document.body.innerHTML = "";
});

describe("the queue's View disclosure is removed by an unfold decided by measurement: focus goes to what it stood for", () => {
  it("focus on View, then the room grows (no rung crossing, no frame): lands on the Group/Order/Display controls, never <body>", async () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    await settle();
    /* A re-measure with the layout in place (the mount's own measure ran before it existed). */
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    await settle();
    const view = c.querySelector<HTMLElement>("button.pq-viewbtn");
    expect(view, "precondition: with 4 rows of room the queue folds its controls under View").not.toBeNull();
    act(() => {
      view!.focus();
    });
    expect(document.activeElement, "precondition: focus is on View").toBe(view);

    portBottom = ROOMY_BOTTOM;
    width = 800;
    /* The re-measure arrives as the browser delivers it: a native callback OUTSIDE React's batching,
       so React commits the unfold in its own later task — not inside an `act()` that commits before
       any microtask queued by the callback can run. That ordering is the defect's: MEASURED, a
       microtask hand-off queued from the callback ran while focus was still on View (and did
       nothing), and the commit after it removed View. Inside `act()` the old hand-off passes by luck
       of ordering, so this step is deliberately not wrapped. */
    globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    try {
      window.dispatchEvent(new Event("resize"));
      await new Promise((r) => setTimeout(r, 100));
    } finally {
      globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    }
    await settle();

    expect(c.querySelector("button.pq-viewbtn"), "precondition: with room again the queue unfolds and View is removed").toBeNull();
    const a = document.activeElement;
    expect(a !== null && a !== document.body && a.isConnected, `the unfold dropped focus (${where()})`).toBe(true);
    const controls = c.querySelector<HTMLElement>(".pq-controls")!;
    expect(controls.contains(a), `focus is not on the controls View stood for (${where()})`).toBe(true);
  });
});
