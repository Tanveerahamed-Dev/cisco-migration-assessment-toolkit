/**
 * FabricLabels.rescue-glyph.test.tsx — the mark's RESCUE never lands a name on the trace's terminal glyph.
 *
 * Composition of two fixes that met in one merge (acceptance A5 x A6). A6 gave a marked label every
 * column search has failed a last resort: `rescueSlot`, which offers it any slot on the stage. A5 made
 * the trace's terminal glyph an obstacle no name may be drawn across (a name across the verdict ring
 * hides the verdict). The column searches refuse the glyph; the rescue only refuses it through its own
 * `taken` predicate. This pins that clause in the composed layer: a marked label whose column searches
 * all fail, and whose nearest rescue slot lies exactly on the glyph, is rescued to a slot CLEAR of it.
 *
 * The scenario is measured in two steps rather than hand-computed, so it cannot silently stop exercising
 * the rescue: first without a glyph, to find the slot the rescue picks (and to prove it is a rescue slot,
 * not one of the column searches' slots); then with the glyph drawn over exactly that slot.
 */
import { act, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels } from "./FabricLabels";

type P = { x: number; y: number; visible: boolean };
interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/* The phone-width stage and HUD of FabricLabels.marks.test.tsx (the A6 refuter's measured shape). */
const STAGE = { w: 390, h: 389 };
const HUD: Box[] = [
  { x: 225, y: 8, w: 83, h: 24 },
  { x: 312, y: 8, w: 70, h: 24 },
  { x: 10, y: 36, w: 372, h: 22 },
  { x: 318, y: 62, w: 64, h: 24 },
];
const LABEL_W = 150;
const LABEL_H = 16;
const NAME_LEFT = 4;
const NAME_W = 72;
/** FabricLabels DECLUTTER_ROW_GUTTER: a column search moves a label by whole (LABEL_H + gutter) rows. */
const COLUMN_STEP = LABEL_H + 6;

const DEVICES: Device[] = fabric.devices.slice(0, 12);
const ids = DEVICES.map((d) => d.id);

let frames = new Map<number, FrameRequestCallback>();
let nextId = 1;
const flush = (n = 1): void => {
  for (let i = 0; i < n; i += 1) {
    const batch = [...frames.values()];
    frames = new Map();
    act(() => {
      for (const cb of batch) cb(0);
    });
  }
};

const rect = (b: Box): DOMRect =>
  ({ left: b.x, top: b.y, right: b.x + b.w, bottom: b.y + b.h, width: b.w, height: b.h, x: b.x, y: b.y, toJSON: () => ({}) }) as DOMRect;
const boxAttr = (b: Box): string => `${b.x},${b.y},${b.w},${b.h}`;
const parseBox = (s: string): Box => {
  const [x, y, w, h] = s.split(",").map(Number) as [number, number, number, number];
  return { x, y, w, h };
};
const overlap = (a: Box, b: Box): boolean => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

const originalRect = HTMLElement.prototype.getBoundingClientRect;

interface Drawn {
  /** The box the label is drawn in, read back from the transform the layer wrote. */
  box: Box;
  visible: boolean;
  covered: boolean;
}

/**
 * Mount the A6 cut-point stage (the cut point under the HUD, a column of neighbours straight below it
 * so every row the label can move to reads as theirs), optionally with the trace's terminal glyph at
 * `glyph` (host: the cut point itself), run the layer to rest and read back the cut point's label.
 */
function placeCutPoint(glyph: Box | null): Drawn {
  const [cut, n1, n2, n3] = ids as [string, string, string, string];
  const proj = new Map<string, P>([
    [cut, { x: 190, y: 20, visible: true }],
    [n1, { x: 190, y: 70, visible: true }],
    [n2, { x: 190, y: 110, visible: true }],
    [n3, { x: 190, y: 150, visible: true }],
  ]);
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.dataset["box"] !== undefined) return rect(parseBox(this.dataset["box"]));
    if (this.classList.contains("stage") || this.classList.contains("fabric3d__labels")) return rect({ x: 0, y: 0, ...STAGE });
    if (this.classList.contains("hud")) {
      const x0 = Math.min(...HUD.map((b) => b.x));
      const y0 = Math.min(...HUD.map((b) => b.y));
      return rect({ x: x0, y: y0, w: Math.max(...HUD.map((b) => b.x + b.w)) - x0, h: Math.max(...HUD.map((b) => b.y + b.h)) - y0 });
    }
    return originalRect.call(this) as DOMRect;
  };
  const scene: Record<string, unknown> = {
    project: (id: string) => proj.get(id) ?? null,
    labelsSettled: () => true,
  };
  if (glyph !== null) {
    scene["terminalGlyphScreenBox"] = () => ({ host: cut, x0: glyph.x, y0: glyph.y, x1: glyph.x + glyph.w, y1: glyph.y + glyph.h });
  }
  const ref: RefObject<FabricScene | null> = { current: scene as unknown as FabricScene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  act(() => {
    root.render(
      <div className="stage">
        <FabricLabels
          devices={DEVICES}
          sceneRef={ref}
          epoch={0}
          hover={createHoverChannel()}
          selectedId={cut}
          cutPointId={cut}
          strandedIds={new Set<string>()}
          strandedQualifier="uncertain"
        />
        <div className="hud" data-label-keepout="">
          {HUD.map((b) => (
            <span key={boxAttr(b)} data-box={boxAttr(b)} />
          ))}
        </div>
      </div>,
    );
  });
  for (const el of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => LABEL_W });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => LABEL_H });
    const name = el.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => NAME_LEFT });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => NAME_W });
  }
  flush(6);
  const el = container.querySelector<HTMLElement>(`[data-device="${cut}"]`)!;
  expect(el.dataset["cut"]).toBe("yes");
  const t = el.style.transform;
  const m = /translate3d\(([-\d.]+)px, ([-\d.]+)px, 0\) translate\(0, ([-\d.]+)%\)/.exec(t);
  if (!m) throw new Error(`unparsed transform for ${cut}: "${t}"`);
  const out: Drawn = {
    box: { x: Number(m[1]), y: Number(m[2]) + (Number(m[3]) / 100) * LABEL_H, w: LABEL_W, h: LABEL_H },
    visible: el.dataset["visible"] === "true",
    covered: el.dataset["covered"] === "yes",
  };
  act(() => root.unmount());
  container.remove();
  return out;
}

beforeEach(() => {
  frames = new Map();
  nextId = 1;
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    const id = nextId;
    nextId += 1;
    frames.set(id, cb);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  vi.unstubAllGlobals();
});

describe("the mark's rescue refuses the trace's terminal glyph (A5 x A6 composition)", () => {
  it("a cut point whose column searches all fail, with its nearest rescue slot on the glyph, is rescued clear of the glyph", () => {
    /* Step 1 — no glyph: find the slot the rescue picks, and prove it IS a rescue. */
    const free = placeCutPoint(null);
    expect(free.visible, "the selected cut point is always labelled").toBe(true);
    expect(free.covered, "the rescue placed it legibly").toBe(false);
    for (const c of HUD) expect(overlap(free.box, c), `rescued ${JSON.stringify(free.box)} under the HUD ${JSON.stringify(c)}`).toBe(false);
    /* Every column search keeps the label's own x and moves it by whole rows of COLUMN_STEP. The home
       x is the name centred on the anchor (190 - (NAME_LEFT + NAME_W / 2)), clamped into the stage. */
    const homeX = Math.min(Math.max(4, Math.round(190 - (NAME_LEFT + NAME_W / 2))), STAGE.w - 4 - LABEL_W);
    const sideways = free.box.x !== homeX;
    /* The flipped home top (the label hangs below an anchor this near the stage top). The rows the
       column searches can reach are this top plus k whole steps, |k| <= 5. */
    const flippedHome = placeCutPointHomeTop();
    const rowOffset = (free.box.y - flippedHome) / COLUMN_STEP;
    const columnRow = Number.isInteger(rowOffset) && Math.abs(rowOffset) <= 5;
    expect(
      sideways || !columnRow,
      `the no-glyph placement ${JSON.stringify(free.box)} is a column-search slot (home x ${homeX}, home top ${flippedHome}), not a rescue — the scenario no longer exercises rescueSlot`,
    ).toBe(true);

    /* Step 2 — the trace's terminal glyph drawn over exactly that slot. The glyph only ADDS obstacles,
       so every column search still fails and the rescue runs again; its nearest slot is now on the
       glyph, which it must refuse. */
    const glyph: Box = { ...free.box };
    const withGlyph = placeCutPoint(glyph);
    expect(withGlyph.visible, "the selected cut point is always labelled").toBe(true);
    expect(withGlyph.covered, "a free slot remains on this stage, so the mark is rescued legibly").toBe(false);
    expect(
      overlap(withGlyph.box, glyph),
      `the rescued cut point ${JSON.stringify(withGlyph.box)} is drawn across the terminal glyph ${JSON.stringify(glyph)}`,
    ).toBe(false);
    for (const c of HUD) expect(overlap(withGlyph.box, c), `rescued ${JSON.stringify(withGlyph.box)} under the HUD ${JSON.stringify(c)}`).toBe(false);
    expect(withGlyph.box.x >= 0 && withGlyph.box.y >= 0 && withGlyph.box.x + LABEL_W <= STAGE.w && withGlyph.box.y + LABEL_H <= STAGE.h).toBe(true);
  });
});

/** The cut point's flipped home top: an anchor at y = 20 under LIFT_BLOCKED, read back from a stage where
 *  nothing displaces it (no HUD, no neighbours), so the arithmetic is the layer's own, not restated. */
function placeCutPointHomeTop(): number {
  const [cut] = ids as [string];
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.classList.contains("stage") || this.classList.contains("fabric3d__labels")) return rect({ x: 0, y: 0, ...STAGE });
    return originalRect.call(this) as DOMRect;
  };
  const scene = { project: (id: string) => (id === cut ? { x: 190, y: 20, visible: true } : null), labelsSettled: () => true };
  const ref: RefObject<FabricScene | null> = { current: scene as unknown as FabricScene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  act(() => {
    root.render(
      <div className="stage">
        <FabricLabels devices={DEVICES} sceneRef={ref} epoch={0} hover={createHoverChannel()} selectedId={cut} cutPointId={cut} />
      </div>,
    );
  });
  for (const el of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => LABEL_W });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => LABEL_H });
    const name = el.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => NAME_LEFT });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => NAME_W });
  }
  flush(6);
  const el = container.querySelector<HTMLElement>(`[data-device="${cut}"]`)!;
  expect(el.dataset["visible"]).toBe("true");
  const m = /translate3d\(([-\d.]+)px, ([-\d.]+)px, 0\) translate\(0, ([-\d.]+)%\)/.exec(el.style.transform);
  if (!m) throw new Error(`unparsed transform: "${el.style.transform}"`);
  const top = Number(m[2]) + (Number(m[3]) / 100) * LABEL_H;
  act(() => root.unmount());
  container.remove();
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  return top;
}
