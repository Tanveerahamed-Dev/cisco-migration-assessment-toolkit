/**
 * PriorityQueue.a4-band.test.tsx — A4: a device pick with no finding selected keeps the reader's
 * place when a row naming the device was on screen WHEN THEY ACTED, wherever in the port that row
 * sat — including the bottom band the count sentence is about to push out.
 *
 * THE DEFECT, measured (acceptance-report.md A4, re-measured on a private dev server 2026-09-25,
 * 1920x1080, light theme, nothing selected): the queue scrolled so F099 — the only visible row naming
 * access13 — sat at 999-1041 in a grid port of 352-1054 (scrollTop 4777). One canvas click on
 * access13 left scrollTop at 0, F099 at y=5814. access5/F094: 4511 -> 0. The pick commits in two
 * steps: the URGENT render mounts "19 of 146 shown findings name access13 — marking the rows." above
 * the grid, which moves the port's top 352 -> 389.7; the DEFERRED render then runs the "is an answer
 * already on screen?" check (`revealUnlessVisible`) against that moved layout, finds F099 38 px under
 * the port's bottom edge, and reveals the first naming row (F002, scrollTop 0).
 *
 * The class: a visibility decision taken against a layout that the same state change is about to
 * move. So these tests sweep the WHOLE band — positions of the naming row from the port's top edge
 * to its bottom edge, every 2 px across the bottom band the sentence pushes out and every 15 px
 * elsewhere — through the real PriorityQueue, under port geometries modelled on the 1920, 1440, 768
 * and 390 px layouts (the 390 layout is page-scrolled in the browser; here it is a short port with
 * a narrow sentence, which is the geometry the jsdom model can state honestly — the real page-scroll
 * case is measured by the Playwright probe in the wave record). EVERY whole-pixel position at each
 * measured viewport is swept against the grid itself in DataGrid.act-view.test.tsx, where a render
 * is cheap enough to afford it. The sentence's height is a function of its TEXT (lines at a fixed
 * characters-per-line), so "marking the rows." -> "marked on the row's trailing edge." can re-wrap
 * inside the deferred commit itself.
 *
 * jsdom has no layout, so it is supplied: the port's top edge sits under the rail's notes, a sticky
 * header rides it, rows are positioned from their index and the live scrollTop.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { useUrlSync } from "../app/urlSync";
import { PriorityQueue } from "./PriorityQueue";
import { describeGolden } from "../test-support/golden-sample";
import { need } from "../test-support/trace-universe";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

interface Geometry {
  name: string;
  /** Viewport height: the band is clipped by it (`visibleBand`). */
  vh: number;
  /** The port's top edge with NO note above the grid, and its fixed bottom edge. */
  top: number;
  bottom: number;
  head: number;
  row: number;
  /** How many characters of a note fit on one line of the rail at this width. */
  cpl: number;
  line: number;
  /** A note's own margin, whatever its length. */
  pad: number;
}

/* Modelled on the measured layouts (review probe, 2026-09-25): 1920x1080 port 352-1054 and one
   sentence line = 37.7 px; 1440x900 port 376-874; 768x1024 port 744-1048, clipped by the viewport at 1024; 390x844 the rail is
   ~358 px wide, so the sentence wraps to two or three lines. */
const GEOMETRIES: Geometry[] = [
  { name: "1920x1080", vh: 1080, top: 352, bottom: 1054, head: 40, row: 47, cpl: 120, line: 20, pad: 17.7 },
  { name: "1440x900", vh: 900, top: 376, bottom: 874, head: 40, row: 47, cpl: 96, line: 20, pad: 17.7 },
  /* The grid's box runs to 1048 there, but the viewport clips it at 1024: that is the band's real edge. */
  { name: "768x1024", vh: 1024, top: 744, bottom: 1024, head: 40, row: 47, cpl: 90, line: 20, pad: 17.7 },
  { name: "390x844", vh: 844, top: 300, bottom: 844, head: 40, row: 56, cpl: 44, line: 20, pad: 4 },
  /* A rail where "— marking the rows." fits one line and "— marked on the row's trailing edge." needs
     two: the DEFERRED commit — the one that takes the decision — re-wraps the sentence itself. */
  { name: "390x844 re-wrapping", vh: 844, top: 300, bottom: 844, head: 40, row: 56, cpl: 60, line: 20, pad: 4 },
];

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

/** The rail's notes above the grid push its top edge down by their wrapped height. */
function notesHeight(c: HTMLElement, g: Geometry): number {
  let h = 0;
  for (const n of c.querySelectorAll<HTMLElement>(".pq-account__note")) {
    const text = n.textContent ?? "";
    if (text === "") continue;
    h += g.pad + Math.ceil(text.length / g.cpl) * g.line;
  }
  return h;
}

function installLayout(container: HTMLElement, g: Geometry): { grid: HTMLElement; portTop: () => number } {
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  let scrollTop = 0;
  Object.defineProperty(grid, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = Math.max(0, v);
    },
  });
  const portTop = (): number => g.top + notesHeight(container, g);
  const original = HTMLElement.prototype.getBoundingClientRect;
  const indexOf = new WeakMap<HTMLElement, number>();
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.classList.contains("ag__grid")) return rect(portTop(), g.bottom);
    if (this.classList.contains("ag__head")) return rect(portTop(), portTop() + g.head);
    if (this.classList.contains("ag__row--data")) {
      /* A device pick marks rows, it never re-orders them, so each row element's index is looked up
         once (a miss — a new element — re-indexes them all). */
      let at = indexOf.get(this);
      if (at === undefined) {
        [...grid.querySelectorAll<HTMLElement>(".ag__row--data")].forEach((r, i) => indexOf.set(r, i));
        at = indexOf.get(this) ?? -1;
      }
      const top = portTop() + g.head + at * g.row - grid.scrollTop;
      return rect(top, top + g.row);
    }
    return original.call(this) as DOMRect;
  };
  const vh = Object.getOwnPropertyDescriptor(window, "innerHeight");
  Object.defineProperty(window, "innerHeight", { configurable: true, value: g.vh });
  restore = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
    if (vh) Object.defineProperty(window, "innerHeight", vh);
  };
  return { grid, portTop };
}

const dataRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>(".ag__row--data")];
const idOf = (row: HTMLElement): string =>
  (row.querySelector('[role="rowheader"]')?.textContent ?? "").trim().split(/[\s,]/)[0] ?? "";

/** Fully inside the band below the sticky header, against the layout as it stands NOW. */
function inView(row: HTMLElement, portTop: () => number, g: Geometry): boolean {
  const r = row.getBoundingClientRect();
  return r.top >= portTop() + g.head - 0.01 && r.bottom <= g.bottom + 0.01;
}

/** The reader scrolls: a wheel precedes the scroll, as it does in a browser. */
function readerScrollsTo(grid: HTMLElement, y: number): void {
  act(() => {
    grid.dispatchEvent(new Event("wheel"));
    grid.scrollTop = y;
    grid.dispatchEvent(new Event("scroll"));
  });
}

/** Drains React, including the deferred re-render the pick schedules. */
async function flush(): Promise<void> {
  await actAsync(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

function namingIndices(c: HTMLElement, host: string): number[] {
  const naming = new Set(fabric.findings.filter((f) => f.devices.includes(host)).map((f) => f.id));
  return dataRows(c)
    .map((r, i) => (naming.has(idOf(r)) ? i : -1))
    .filter((i) => i !== -1);
}

/** The scrollTop that puts data row `n`'s top `o` px below the band's top edge (the header's lower
 *  edge), whatever the port's top is — rows are laid out from it. */
const scrollFor = (n: number, o: number, g: Geometry): number => n * g.row - o;

/** For offset `o` in a band `bandPx` tall, a naming row that — scrolled to `o` — is the ONLY naming
 *  row fully visible: the report's shape exactly. Every naming row is tried, so every offset of the
 *  band is reachable, not only those one chosen row allows. */
function soleNamingRowAt(o: number, idx: readonly number[], g: Geometry, bandPx: number): number | null {
  for (const n of idx) {
    const start = scrollFor(n, o, g);
    if (start < 0) continue;
    const visible = idx.filter((i) => {
      const top = i * g.row - start;
      return top >= 0 && top + g.row <= bandPx;
    });
    if (visible.length === 1 && visible[0] === n) return n;
  }
  return null;
}

/** How far the pick's sentence ("N of 146 shown findings name <host> — marked on the row's trailing
 *  edge.", ~75 characters) moves the port in this geometry: the band in which a visible row is pushed
 *  out, and where the decision under test changes. */
const shiftOf = (g: Geometry): number => g.pad + Math.ceil(76 / g.cpl) * g.line;

/** Offsets of a row's top below the band's top edge, from the top edge (0) to the bottom edge
 *  (`bandPx - row`): every 2 px across the bottom band the sentence pushes out (plus 6 px of margin),
 *  every 15 px elsewhere, and both extremes and the band's boundary exactly. Outside the pushed-out
 *  band the row stays visible whatever the fix, so the dense sampling is where the behaviour can
 *  differ; the sparse sampling proves the rest of the band is not disturbed. */
function offsets(g: Geometry, bandPx: number): number[] {
  const last = Math.floor(bandPx - g.row);
  const dense = Math.ceil(shiftOf(g)) + 6;
  const edge = Math.floor(last - shiftOf(g));
  const out = new Set<number>([0, last, edge, edge + 1, edge - 1].filter((o) => o >= 0 && o <= last));
  for (let o = 0; o <= last; o += 1) {
    if ((o >= last - dense && (last - o) % 2 === 0) || o % 15 === 0) out.add(o);
  }
  return [...out].sort((a, b) => a - b);
}

/** The band a row can be fully visible in, against the port as it stands now. */
const bandNow = (portTop: () => number, g: Geometry): number => g.bottom - portTop() - g.head;

const pickDevice = (host: string | null): void => useInvestigation.getState().selectDevice(host, { surface: "fabric" });

/**
 * The hosts the picks are made on, read from the snapshot by how many findings name them (ties by name),
 * not named — phase 3 rename leg: "access13", "core1" and "access5" are the sample's names for the
 * measured cases, which stay pinned by name in the golden blocks. MOST is the most named host (the
 * device a reader selects first), HEAVY the second most named (named on many screens, never all).
 */
const BY_NAMING: readonly string[] = (() => {
  const n = new Map<string, number>();
  for (const f of fabric.findings) for (const d of new Set(f.devices)) n.set(d, (n.get(d) ?? 0) + 1);
  return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([h]) => h);
})();
const MOST = (): string => {
  expect(BY_NAMING[0], "precondition: some finding names a host").toBeDefined();
  return BY_NAMING[0]!;
};
const HEAVY = (): string => {
  expect(BY_NAMING[1], "precondition: two hosts are named by findings").toBeDefined();
  return BY_NAMING[1]!;
};

/**
 * The host a band test picks, found by the PROPERTY the test needs in the mounted queue (verifier V5,
 * phase 3): the first host in naming order starting from the second most named (HEAVY — the measured
 * access13 on the reference sample, pinned in the golden block), then the most named, whose naming rows
 * satisfy `ok`. On the engine's golden fleet the second most named host is named by nearly every row, so
 * no offset shows it alone and no offset shows none of it; a smaller host still does. Undefined when no
 * host of the snapshot has the property — the caller skips by name through `need`.
 */
function subjectHost(c: HTMLElement, ok: (idx: readonly number[]) => boolean, exclude: string | null = null): string | undefined {
  const order = [...BY_NAMING.slice(1), ...BY_NAMING.slice(0, 1)];
  return order.find((h) => h !== exclude && ok(namingIndices(c, h)));
}
/** Every offset of the band has a naming row that is the only one visible there. */
const soleAtEveryOffset = (g: Geometry, bandPx: number) => (idx: readonly number[]): boolean =>
  idx.length > 0 && offsets(g, bandPx).every((o) => soleNamingRowAt(o, idx, g, bandPx) !== null);
/** Some scroll position after the first naming row shows no naming row at all. */
const someOffsetShowsNone = (rowCount: number, g: Geometry, bandPx: number) => (idx: readonly number[]): boolean => {
  if (idx.length === 0) return false;
  for (let i = idx[0]! + 1; i < rowCount; i += 1) {
    const start = scrollFor(i, 0, g);
    if (idx.every((k) => { const top = k * g.row - start; return !(top >= 0 && top + g.row <= bandPx); })) return true;
  }
  return false;
};

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
  act(() => { useInvestigation.getState().reset(); });
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

/**
 * One sweep: for each offset of the band, start from `from` (null = nothing selected), scroll so a
 * row naming `host` is the ONLY visible naming row and sits at that offset, pick `host`, and record
 * every offset at which the reader lost it or the list moved further than the layout did.
 */
async function sweep(
  g: Geometry,
  hostOrProperty: string | null,
  from: string | null,
): Promise<{ host: string | null; failures: string[]; checked: number; maxShift: number }> {
  const c = mount(<PriorityQueue debounceMs={0} />);
  const { grid, portTop } = installLayout(c, g);
  const failures: string[] = [];
  let checked = 0;
  let maxShift = 0;
  act(() => { pickDevice(from); });
  await flush();
  const band0 = bandNow(portTop, g);
  /* `null`: the host is the first one (from the second most named) whose naming rows put a sole visible
     naming row at every offset of this band — the property the sweep needs. */
  const host = hostOrProperty ?? subjectHost(c, soleAtEveryOffset(g, band0), from) ?? null;
  if (host === null) return { host, failures, checked, maxShift };
  const idx = namingIndices(c, host);
  for (const o of offsets(g, band0)) {
    act(() => { pickDevice(from); });
    await flush();
    const n = soleNamingRowAt(o, idx, g, bandNow(portTop, g));
    if (n === null) throw new Error(`precondition: no row naming ${host} is the only one visible at offset ${o}`);
    const start = scrollFor(n, o, g);
    readerScrollsTo(grid, start);
    const rows = dataRows(c);
    const visibleNaming = idx.filter((i) => inView(rows[i]!, portTop, g));
    if (visibleNaming.length !== 1 || visibleNaming[0] !== n) {
      throw new Error(`precondition at offset ${o}: visible naming rows [${visibleNaming.join(",")}], expected only ${n}`);
    }
    const top0 = portTop();

    act(() => { pickDevice(host); });
    await flush();

    expect(useInvestigation.getState().deviceId).toBe(host);
    const note = c.querySelector(".pq-account__note")?.textContent ?? "";
    expect(note, "the deferred commit (the marks) has landed").toContain("marked on the row's trailing edge");
    const shift = Math.abs(portTop() - top0);
    maxShift = Math.max(maxShift, shift);
    const moved = Math.abs(grid.scrollTop - start);
    checked += 1;
    /* The reader could see row n when they acted. Afterwards it must still be fully visible, and the
       list may move by no more than the layout itself moved — the least movement that keeps it. */
    if (!inView(dataRows(c)[n]!, portTop, g) || moved > shift + 0.5) {
      failures.push(
        `offset ${o}: scrollTop ${start} -> ${grid.scrollTop} (port moved ${shift.toFixed(1)} px), row ${n} in view: ${inView(dataRows(c)[n]!, portTop, g)}`,
      );
    }
  }
  return { host, failures, checked, maxShift };
}

describe("A4: the whole band — a naming row visible when the reader acted keeps their place", () => {
  for (const g of GEOMETRIES) {
    it(`${g.name}: the second most named host picked with nothing selected, the only visible naming row at every offset from the top to the bottom edge`, async (ctx) => {
      const { host, failures, checked, maxShift } = await sweep(g, null, null);
      need(ctx, host, "host whose naming rows leave one of them alone at every offset of the band");
      expect(maxShift, "the model must move the port on the pick (else this proves nothing)").toBeGreaterThan(20);
      expect(checked).toBeGreaterThan(30);
      expect(failures, `${failures.length} of ${checked} offsets lost the reader's place:\n${failures.slice(0, 8).join("\n")}`).toEqual([]);
    }, 180_000);
  }

  for (const g of [GEOMETRIES[0]!]) {
    it(`${g.name}: device-to-device — the most named host selected, then the second most named picked (the sentence re-words; the port does not move, and neither may the list)`, async (ctx) => {
      const { host, failures, checked } = await sweep(g, null, MOST());
      need(ctx, host, "second host whose naming rows leave one of them alone at every offset of the band");
      expect(checked).toBeGreaterThan(30);
      expect(failures, `${failures.length} of ${checked} offsets lost the reader's place:\n${failures.slice(0, 8).join("\n")}`).toEqual([]);
    }, 180_000);
  }

  describeGolden("the measured device-to-device case", () => {
    for (const g of [GEOMETRIES[0]!]) {
      it(`${g.name}: device-to-device — core1 selected, then access5 picked (the sentence re-words; the port does not move, and neither may the list)`, async () => {
        const { failures, checked } = await sweep(g, "access5", "core1");
        expect(checked).toBeGreaterThan(30);
        expect(failures, `${failures.length} of ${checked} offsets lost the reader's place:\n${failures.slice(0, 8).join("\n")}`).toEqual([]);
      }, 180_000);
    }
    it("the hosts the property picks are the measured ones", () => {
      expect([MOST(), HEAVY()]).toEqual(["core1", "access13"]);
    });
    it("on the reference sample the band property picks the second most named host itself, at every geometry", async () => {
      for (const g of GEOMETRIES) {
        const c = mount(<PriorityQueue debounceMs={0} />);
        const { portTop } = installLayout(c, g);
        const band = bandNow(portTop, g);
        expect(subjectHost(c, soleAtEveryOffset(g, band)), g.name).toBe(HEAVY());
        expect(subjectHost(c, someOffsetShowsNone(dataRows(c).length, g, band)), g.name).toBe(HEAVY());
        for (const m of mounted.splice(0)) {
          act(() => m.root.unmount());
          m.container.remove();
        }
        restore?.();
        restore = null;
      }
    });
  });

  describeGolden("the report's exact case", () => {
  it("1920x1080: the report's exact case — F099 13 px above the port's bottom edge, access13 picked: scrollTop does not fall to 0", async () => {
    const g = GEOMETRIES[0]!;
    const c = mount(<PriorityQueue debounceMs={0} />);
    const { grid, portTop } = installLayout(c, g);
    const rows = dataRows(c);
    const n = rows.findIndex((r) => idOf(r) === "F099");
    expect(n).toBeGreaterThan(-1);
    const start = scrollFor(n, bandNow(portTop, g) - 13 - g.row, g);
    readerScrollsTo(grid, start);
    expect(namingIndices(c, "access13").filter((i) => inView(rows[i]!, portTop, g)), "F099 is the only naming row visible").toEqual([n]);
    act(() => { pickDevice("access13"); });
    await flush();
    expect(grid.scrollTop, `scrollTop ${start} -> ${grid.scrollTop}`).not.toBe(0);
    expect(Math.abs(grid.scrollTop - start)).toBeLessThanOrEqual(38);
    expect(inView(dataRows(c)[n]!, portTop, g), "F099 stays fully visible").toBe(true);
  });
  });

  it("centred control: the only naming row mid-port does not move the list at all", async (ctx) => {
    const g = GEOMETRIES[0]!;
    const c = mount(<PriorityQueue debounceMs={0} />);
    const { grid, portTop } = installLayout(c, g);
    const o = Math.round((bandNow(portTop, g) - g.row) / 2);
    const host = need(
      ctx,
      subjectHost(c, (idx) => soleNamingRowAt(o, idx, g, bandNow(portTop, g)) !== null),
      "host with a naming row alone mid-port",
    );
    const n = soleNamingRowAt(o, namingIndices(c, host), g, bandNow(portTop, g));
    expect(n, "precondition: some naming row is alone mid-port").not.toBeNull();
    const start = scrollFor(n!, o, g);
    readerScrollsTo(grid, start);
    act(() => { pickDevice(host); });
    await flush();
    expect(grid.scrollTop).toBe(start);
  });

  it("negative control: with NO naming row visible, the first naming row is still revealed", async (ctx) => {
    const g = GEOMETRIES[0]!;
    const c = mount(<PriorityQueue debounceMs={0} />);
    const { grid, portTop } = installLayout(c, g);
    const host = need(
      ctx,
      subjectHost(c, someOffsetShowsNone(dataRows(c).length, g, bandNow(portTop, g))),
      "host some scroll position shows none of the naming rows of",
    );
    const idx = namingIndices(c, host);
    /* The first offset past the first naming row at which no naming row is in view (was "row 30": rows
       27-58 name no access13 on the sample) — found, not typed. */
    const rows = dataRows(c);
    let start = -1;
    for (let i = (idx[0] ?? 0) + 1; i < rows.length && start < 0; i += 1) {
      readerScrollsTo(grid, scrollFor(i, 0, g));
      if (idx.every((k) => !inView(rows[k]!, portTop, g))) start = scrollFor(i, 0, g);
    }
    expect(start, "precondition: some offset shows no naming row").toBeGreaterThan(-1);
    readerScrollsTo(grid, start);
    expect(idx.every((i) => !inView(dataRows(c)[i]!, portTop, g)), "precondition: no naming row visible").toBe(true);
    act(() => { pickDevice(host); });
    await flush();
    expect(inView(dataRows(c)[idx[0]!]!, portTop, g), "the first naming row is revealed").toBe(true);
  });
});

/* ── Browser Back onto a device selection ───────────────────────────────────────────────────────
 * The popstate path writes the store from `urlSync`, not from a surface; it must be answered the
 * same way. */
function Sync(): null {
  useUrlSync({
    schedule: (fn) => {
      const t = setTimeout(fn, 0);
      return () => clearTimeout(t);
    },
  });
  return null;
}

describe("A4: browser Back onto a device selection keeps the reader's place", () => {
  it("1920x1080: the only visible naming row 2 px above the bottom edge survives Back to ?d=<the picked host>", async () => {
    const host = HEAVY();
    const g = GEOMETRIES[0]!;
    window.history.replaceState(null, "", "/");
    const c = mount(
      <>
        <Sync />
        <PriorityQueue debounceMs={0} />
      </>,
    );
    const { grid, portTop } = installLayout(c, g);
    const idx = namingIndices(c, host);
    act(() => { pickDevice(host); });
    await flush();
    const withDevice = window.location.search;
    expect(withDevice).toContain(`d=${encodeURIComponent(host)}`);
    act(() => { pickDevice(null); });
    await flush();
    expect(window.location.search).not.toContain(`d=${encodeURIComponent(host)}`);
    const o = bandNow(portTop, g) - 2 - g.row;
    const n = soleNamingRowAt(o, idx, g, bandNow(portTop, g));
    expect(n, "precondition: some naming row is alone at the bottom edge").not.toBeNull();
    const start = scrollFor(n!, o, g);
    readerScrollsTo(grid, start);
    expect(idx.filter((i) => inView(dataRows(c)[i]!, portTop, g))).toEqual([n]);
    const top0 = portTop();
    // Back: the browser restores the earlier entry, then fires popstate.
    window.history.replaceState(null, "", withDevice);
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await flush();
    expect(useInvestigation.getState().deviceId).toBe(host);
    const shift = portTop() - top0;
    expect(shift).toBeGreaterThan(20);
    expect(grid.scrollTop, `scrollTop ${start} -> ${grid.scrollTop}`).not.toBe(0);
    expect(Math.abs(grid.scrollTop - start)).toBeLessThanOrEqual(shift + 0.5);
    expect(inView(dataRows(c)[n!]!, portTop, g)).toBe(true);
  });
});

