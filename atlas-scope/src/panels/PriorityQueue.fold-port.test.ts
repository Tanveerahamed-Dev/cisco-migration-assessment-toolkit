/**
 * PriorityQueue.fold-port.test.ts — the view-controls fold (O24) reads the queue's OWN port, never
 * the page's scroll.
 *
 * THE DEFECT (merged-tree gate, wave 5, 2026-09-24). `restingRowsInView` counts the rows inside
 * "every clipping ancestor", and below 768 px the only such ancestor is <body>, whose `overflow:
 * auto` propagates to the VIEWPORT (shell.css: the page itself scrolls there). So the fold measured
 * the viewport as the queue's port: its answer moved with page scroll (body.scrollTop stays 0 while
 * the window scrolls, so nothing undid it — against this function's own "the answer does not change
 * as the reader scrolls") and with anything laid out above the queue. MEASURED at 390x844 on the
 * preview: with the phone Inspector sheet open above the rails the grid started at y=681, fewer than
 * six rows "fitted", and the queue folded Group / Order / Display behind "View" part-way through a
 * session — review/audit-d3-focus.mjs: "phone/inspector (i) popover \"Display\" :: NOT DRIVEN
 * (trigger not found after re-entering the state)". Folding there can never put a row on screen —
 * the page scrolls — which is exactly the "futile" fold this feature exists to undo.
 *
 * THE RULE: the document's own scroller (the root, or <body> when its overflow is `auto`/`scroll`
 * and so belongs to the viewport) is not a port of the queue. A fixed frame's `overflow: hidden`
 * body (768 px and up) still is.
 *
 * jsdom lays nothing out, so boxes are stated here; what is under test is which ancestors bound
 * the count. The rendered evidence is review/audit-d3-focus.mjs at 390 and layout-guard's 2c.
 */
import { afterEach, describe, expect, it } from "vitest";
import { restingRowsInView } from "./PriorityQueue";

type Box = { top: number; height: number };
const place = (el: Element, b: Box): void => {
  Object.defineProperty(el, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ top: b.top, bottom: b.top + b.height, height: b.height, left: 0, right: 390, width: 390, x: 0, y: b.top, toJSON: () => ({}) }),
  });
};

let restore: (() => void) | null = null;
afterEach(() => {
  restore?.();
  restore = null;
  document.body.innerHTML = "";
});

/** A queue whose grid starts at y=681 (under the phone Inspector sheet), 146 rows of 45 px. */
function mount(bodyOverflow: string): HTMLElement {
  const prev = document.body.style.overflowY;
  document.body.style.overflowY = bodyOverflow;
  const bodyHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
  Object.defineProperty(document.body, "clientHeight", { configurable: true, value: 844 });
  place(document.body, { top: 0, height: 844 });
  restore = () => {
    document.body.style.overflowY = prev;
    if (bodyHeight) delete (document.body as unknown as Record<string, unknown>)["clientHeight"];
    delete (document.body as unknown as Record<string, unknown>)["getBoundingClientRect"];
  };
  const root = document.createElement("div");
  const grid = document.createElement("div");
  grid.className = "ag__grid";
  const head = document.createElement("div");
  head.className = "ag__row--head";
  place(head, { top: 681, height: 40 });
  grid.appendChild(head);
  for (let i = 0; i < 146; i += 1) {
    const row = document.createElement("div");
    row.className = "ag__row--data";
    place(row, { top: 721 + i * 45, height: 45 });
    grid.appendChild(row);
  }
  place(grid, { top: 681, height: 40 + 146 * 45 });
  root.appendChild(grid);
  document.body.appendChild(root);
  return root;
}

describe("the fold's port is the queue's, not the page's", () => {
  it("a fixed frame's overflow:hidden body still bounds the count (positive control)", () => {
    const root = mount("hidden");
    // Rows start at 721 and are 45 px: centres 743.5, 788.5 and 833.5 are above 844 — three.
    expect(restingRowsInView(root, 0)).toBe(3);
  });

  it("a body whose overflow scrolls the page does not: every laid-out row is reachable", () => {
    const root = mount("auto");
    expect(restingRowsInView(root, 0)).toBe(146);
  });
});
