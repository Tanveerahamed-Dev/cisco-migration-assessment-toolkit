/**
 * PriorityQueue.a4-scroll.test.tsx — A4: with NO finding selected, a device pick keeps the reader's
 * scroll position when a row naming that device is already on screen, and reveals the first naming
 * row only when none is.
 *
 * THE DEFECT, measured in the running app (1920x1080, `?s=queue`, no finding selected): the reader
 * had scrolled the queue to scrollTop 3200, where F060 and F069 — both naming access13 — were in
 * view. Picking access13 on the canvas, in the Fabric list or from the palette left the queue at
 * 3200 for ~80 ms, then threw it to 0 once the deferred marks committed (core2: 3200 -> 2681, dist1
 * the same). With no finding active, `revealId` is the FIRST row naming the device and `revealKey`
 * is the whole device/link/hop selection, so every device pick re-ran the grid's reveal and centred
 * F002 even though the reader was already looking at rows that answer "what names access13".
 *
 * All three surfaces end in the same store call (`selectDevice(host, { surface: "fabric" })` —
 * Fabric3D.tsx, FabricA11yTree.tsx, CommandPalette.tsx), so one pick per host exercises all three
 * here; the in-browser measurement of the real surfaces is a Playwright probe (see the wave record).
 *
 * jsdom has no layout, so it is supplied exactly as in PriorityQueue.reveal-hold.test.tsx: a fixed
 * scroll port, a sticky header on its top edge, uniform rows positioned from their index and the
 * live scrollTop.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { PriorityQueue } from "./PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PORT_TOP = 0;
const PORT_BOTTOM = 561;
const HEAD_PX = 40;
const ROW_PX = 47;
/** A4's own settle bar: the defect showed the right scrollTop at 80 ms and the wrong one later. */
const SETTLE_MS = 500;

const mounted: { root: Root; container: HTMLElement }[] = [];
let restore: (() => void) | null = null;

const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: 900, width: 900, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

function installLayout(container: HTMLElement): HTMLElement {
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  let scrollTop = 0;
  Object.defineProperty(grid, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = Math.max(0, v);
    },
  });
  const original = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.classList.contains("ag__grid")) return rect(PORT_TOP, PORT_BOTTOM);
    if (this.classList.contains("ag__head")) return rect(PORT_TOP, PORT_TOP + HEAD_PX);
    if (this.classList.contains("ag__row--data")) {
      const owner = this.closest<HTMLElement>(".ag__grid");
      const rows = owner ? [...owner.querySelectorAll<HTMLElement>(".ag__row--data")] : [];
      const top = PORT_TOP + HEAD_PX + rows.indexOf(this) * ROW_PX - (owner?.scrollTop ?? 0);
      return rect(top, top + ROW_PX);
    }
    return original.call(this) as DOMRect;
  };
  restore = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
  };
  return grid;
}

const dataRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>(".ag__row--data")];
const idOf = (row: HTMLElement): string =>
  (row.querySelector('[role="rowheader"]')?.textContent ?? "").trim().split(/[\s,]/)[0] ?? "";
const inView = (row: HTMLElement): boolean => {
  const r = row.getBoundingClientRect();
  return r.top >= PORT_TOP + HEAD_PX - 1 && r.bottom <= PORT_BOTTOM + 1;
};

/** The reader scrolls: a wheel precedes the scroll, as it does in a browser. */
function readerScrollsTo(grid: HTMLElement, y: number): void {
  act(() => {
    grid.dispatchEvent(new Event("wheel"));
    grid.scrollTop = y;
    grid.dispatchEvent(new Event("scroll"));
  });
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, SETTLE_MS));
  });
}

/** Row indices (in the grid's DOM order) of the findings that name `host`. */
function namingIndices(c: HTMLElement, host: string): number[] {
  const naming = new Set(fabric.findings.filter((f) => f.devices.includes(host)).map((f) => f.id));
  return dataRows(c)
    .map((r, i) => (naming.has(idOf(r)) ? i : -1))
    .filter((i) => i !== -1);
}

beforeEach(() => {
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
  act(() => useInvestigation.getState().reset());
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  restore?.();
  restore = null;
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  document.body.innerHTML = "";
});

/* Every surface a device is picked from — the fabric canvas, the Fabric list, the command palette —
   ends in this ONE store call, so one pick per host exercises all three; running it three times
   under three names would be ceremony, not coverage. */
const pickDevice = (host: string): void => useInvestigation.getState().selectDevice(host, { surface: "fabric" });

describe("A4: a device pick with no finding selected keeps the reader's place when it already answers", () => {
  for (const host of ["access13", "core2", "dist1"]) {
    it(`${host}: scrollTop is unchanged when a row naming it is already visible`, async () => {
      const c = mount(<PriorityQueue debounceMs={0} />);
      const grid = installLayout(c);
      expect(useInvestigation.getState().findingId, "this case is about NO finding selected").toBeNull();

      const idx = namingIndices(c, host);
      expect(idx.length, `${host} must be named by at least two findings`).toBeGreaterThan(1);
      const first = idx[0]!;
      /* A naming row far enough below the first that the first cannot share the port with it. */
      const later = idx.find((i) => (i - first) * ROW_PX > PORT_BOTTOM);
      expect(later, `${host} needs a naming row a full port below the first`).toBeDefined();
      const start = later! * ROW_PX - 200;
      readerScrollsTo(grid, start);
      const rows = dataRows(c);
      expect(inView(rows[later!]!), "precondition: a row naming the device is on screen").toBe(true);
      expect(inView(rows[first]!), "precondition: the FIRST naming row is not").toBe(false);

      act(() => pickDevice(host));
      await settle();

      expect(useInvestigation.getState().deviceId, "the pick must have landed").toBe(host);
      expect(c.querySelectorAll('[data-related="yes"]').length, "the naming rows must be marked").toBe(idx.length);
      expect(grid.scrollTop, "the reader's scroll position must survive").toBe(start);
    });

    it(`${host}: the first naming row IS revealed when no naming row is visible`, async () => {
      const c = mount(<PriorityQueue debounceMs={0} />);
      const grid = installLayout(c);
      const idx = namingIndices(c, host);
      const first = idx[0]!;
      /* Find a scroll offset at which no row naming the host is in view. */
      const rows = dataRows(c);
      let start = -1;
      for (let y = (first + 1) * ROW_PX; y < rows.length * ROW_PX; y += ROW_PX) {
        readerScrollsTo(grid, y);
        if (idx.every((i) => !inView(rows[i]!))) {
          start = y;
          break;
        }
      }
      expect(start, `precondition: some scroll offset shows no row naming ${host}`).toBeGreaterThan(-1);

      act(() => pickDevice(host));
      await settle();

      expect(grid.scrollTop, "the queue must have re-aimed").not.toBe(start);
      expect(inView(dataRows(c)[first]!), "the first row naming the device is in view").toBe(true);
    });
  }

  it("focus returning to the grid after the pick (the palette closing) stays on the answer in view", async () => {
    /* MEASURED (1920x1080, dev build, 2026-09-23) after the scroll half was fixed: with focus on the
       F060 cell at scrollTop 3200, Ctrl+K -> "access13" -> Enter left the queue at 70 with focus on
       F002. The skipped reveal still moved the ROVING cell to the first naming row, and the palette
       returning focus to the grid re-entered on that roving cell, which paged the list to it. The
       roving cell must follow what the reader is looking at — a naming row already in view. */
    const host = "access13";
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const idx = namingIndices(c, host);
    const first = idx[0]!;
    const later = idx.find((i) => (i - first) * ROW_PX > PORT_BOTTOM)!;
    const start = later * ROW_PX - 200;
    readerScrollsTo(grid, start);
    const cell = dataRows(c)[later]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus({ preventScroll: true }));
    expect(document.activeElement).toBe(cell);

    // The palette takes focus, the pick lands, the palette gives focus back to its invoker.
    const palette = document.createElement("input");
    document.body.appendChild(palette);
    act(() => palette.focus());
    act(() => pickDevice(host));
    await settle();
    act(() => cell.focus({ preventScroll: true }));
    await settle();
    palette.remove();

    expect(grid.scrollTop, "focus returning must not page the list away from the answer").toBe(start);
    const focusedRow = (document.activeElement as HTMLElement).closest<HTMLElement>(".ag__row--data");
    expect(focusedRow, "focus must be on a data row").not.toBeNull();
    expect(inView(focusedRow!), "the focused row is in view").toBe(true);
    expect(idx, "and it names the picked device").toContain(dataRows(c).indexOf(focusedRow!));
  });

  it("the grid OWNS focus when the selection's marks commit: focus and scroll both stay on the answer", async () => {
    /* The browser's actual order in the measurement above: Enter closes the palette and focus is
       back on the F060 cell BEFORE the deferred marks commit, so the grid owns focus at the moment
       the reveal target changes — and the focus-follows-roving effect used to move focus (and the
       list) to F002 before any reveal decision ran. */
    const host = "access13";
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const idx = namingIndices(c, host);
    const first = idx[0]!;
    const later = idx.find((i) => (i - first) * ROW_PX > PORT_BOTTOM)!;
    const start = later * ROW_PX - 200;
    readerScrollsTo(grid, start);
    const cell = dataRows(c)[later]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus({ preventScroll: true }));

    act(() => pickDevice(host));
    await settle();

    expect(grid.scrollTop, "the list must not move under the reader's focus").toBe(start);
    expect(document.activeElement, "focus stays on the cell the reader was on — it already names the device").toBe(cell);
  });

  it("with a finding selected, the with-finding behaviour is unchanged: a device pick does not move the queue", async () => {
    /* The half of A4 that passes (PriorityQueue.reveal-hold.test.tsx pins it in depth); restated
       here so this file's change cannot trade one half for the other. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const rows = dataRows(c);
    const id = idOf(rows.at(-1)!);
    act(() => useInvestigation.getState().selectFinding(id));
    expect(inView(rows.at(-1)!)).toBe(true);
    readerScrollsTo(grid, 47);
    act(() => pickDevice("access13"));
    await settle();
    expect(grid.scrollTop).toBe(47);
  });
});
