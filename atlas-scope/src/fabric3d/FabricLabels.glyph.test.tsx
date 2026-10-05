/**
 * FabricLabels.glyph.test.tsx — no name is drawn across the trace's terminal glyph (acceptance A5).
 *
 * MEASURED (independent refuter, A5, r8-zoom.png, 2026-10-02): after Reset view on a core2 -> core1
 * trace, core1 sat near the top of the stage, its label flipped BELOW its anchor (FabricLabels'
 * top-edge rule) — and the anchor of the glyph host is the glyph's top, so the flipped name landed
 * straight across the open UNDECIDED ring it belongs with. The label layer treated every chassis
 * body as an obstacle but knew nothing of the glyph floating above one. The scene now reports the
 * glyph's screen box (`terminalGlyphScreenBox`) and the layer keeps every name off it, its own
 * host's included.
 */
import { act, useCallback, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels } from "./FabricLabels";

type P = { x: number; y: number; visible: boolean };
type ScreenBox = { x0: number; y0: number; x1: number; y1: number };

const [X, Y] = fabric.devices.filter((d) => d.collected) as [Device, Device];
const DEVICES: Device[] = [X, Y];
const W = 100;
const H = 16;
/** FabricLabels LIFT: an UNDECIDED host's label hangs this many label heights above its anchor. */
const LIFT = 1.6;

let frames = new Map<number, FrameRequestCallback>();
let nextId = 1;
const flush = (n = 1): void => {
  for (let i = 0; i < n; i += 1) {
    const batch = [...frames.values()];
    frames = new Map();
    for (const cb of batch) cb(0);
  }
};

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
  vi.unstubAllGlobals();
});

const rect = (b: ScreenBox) =>
  (): DOMRect => ({ left: b.x0, top: b.y0, right: b.x1, bottom: b.y1, width: b.x1 - b.x0, height: b.y1 - b.y0, x: b.x0, y: b.y0, toJSON: () => ({}) }) as DOMRect;
const STAGE: ScreenBox = { x0: 0, y0: 0, x1: 1200, y1: 800 };

/**
 * Mount the layer over a scene whose glyph host projects at `anchor` with its glyph at `glyph`, and,
 * when given, a stage chrome keep-out (the toolbar) at `keepout`.
 */
function labelBoxOf(anchor: P, glyph: ScreenBox, keepout: ScreenBox | null = null): ScreenBox {
  const proj = new Map<string, P>([
    [X.id, anchor],
    [Y.id, { x: 900, y: 500, visible: true }],
  ]);
  const scene = {
    project: (id: string) => proj.get(id) ?? null,
    labelsSettled: () => true,
    terminalGlyphScreenBox: () => ({ host: X.id, ...glyph }),
  } as unknown as FabricScene;
  const ref: RefObject<FabricScene | null> = { current: scene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  function Stage() {
    /* Ref callbacks run before the layer's effect, so the stage and the keep-out are measured with
       these boxes, as the observer would report them. */
    const stageRef = useCallback((el: HTMLDivElement | null) => {
      const labels = el?.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]');
      if (labels) labels.getBoundingClientRect = rect(STAGE);
    }, []);
    const keepoutRef = useCallback((el: HTMLDivElement | null) => {
      if (el && keepout !== null) el.getBoundingClientRect = rect(keepout);
    }, []);
    return (
      <div ref={stageRef}>
        <FabricLabels
          devices={DEVICES}
          sceneRef={ref}
          epoch={0}
          hover={createHoverChannel()}
          selectedId={null}
          alarm={{ id: X.id, kind: "undetermined" }}
        />
        {keepout !== null ? <div data-label-keepout="" ref={keepoutRef} /> : null}
      </div>
    );
  }
  act(() => root.render(<Stage />));
  const overlay = container.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]')!;
  overlay.getBoundingClientRect = rect(STAGE);
  for (const el of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => W });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => H });
    const name = el.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => 20 });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => 60 });
  }
  flush(6);
  const el = container.querySelector<HTMLElement>(`.fabric3d-label[data-device="${X.id}"]`)!;
  expect(el.dataset.visible).toBe("true");
  // translate3d(left, Y, 0) translate(0, -LIFT * 100 %): the box's top is Y - LIFT * H.
  const m = /translate3d\(([-\d.]+)px, ([-\d.]+)px, 0\)/.exec(el.style.transform);
  expect(m).not.toBeNull();
  const left = Number(m![1]);
  const top = Number(m![2]) - LIFT * H;
  act(() => root.unmount());
  container.remove();
  return { x0: left, y0: top, x1: left + W, y1: top + H };
}

const overlaps = (a: ScreenBox, b: ScreenBox): boolean => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;

describe("a label is never drawn across the trace's terminal glyph (acceptance A5)", () => {
  it("the glyph host near the stage top: its flipped name clears the ring", () => {
    // The glyph's top is the anchor (scene.ts projectLabelAnchor), 12 px below the stage top: the
    // name cannot hang above it, so it flips below — and must land below the ring, not on it.
    const glyph = { x0: 380, y0: 12, x1: 420, y1: 52 };
    const box = labelBoxOf({ x: 400, y: 12, visible: true }, glyph);
    expect(overlaps(box, glyph), `label ${JSON.stringify(box)} vs glyph ${JSON.stringify(glyph)}`).toBe(false);
  });

  it("with the stage chrome over its home slot, the name is never displaced onto the ring", () => {
    /* MEASURED (390x844, core1 -> dist1, this fix's own browser probe): the phone toolbar wraps to
       three rows over the chip's home slot; every nearby slot was taken, and the forced label's last
       resort — which accepts a slot over hardware — put "core1 ? UNDECIDED" across the ring. A name
       across a chassis still reads; a name across the verdict glyph hides the verdict. */
    const glyph = { x0: 370, y0: 100, x1: 430, y1: 160 };
    const toolbar = { x0: 0, y0: 0, x1: 1200, y1: 92 };
    const box = labelBoxOf({ x: 400, y: 100, visible: true }, glyph, toolbar);
    expect(overlaps(box, glyph), `label ${JSON.stringify(box)} vs glyph ${JSON.stringify(glyph)}`).toBe(false);
  });

  it("with room above, the name still hangs above the glyph as before", () => {
    const glyph = { x0: 380, y0: 300, x1: 420, y1: 340 };
    const box = labelBoxOf({ x: 400, y: 300, visible: true }, glyph);
    expect(box.y1).toBeLessThanOrEqual(glyph.y0);
  });
});
