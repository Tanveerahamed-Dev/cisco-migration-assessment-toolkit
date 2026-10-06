/** Synthetic A6 placement and reporting controls; no historical render receipt is reused. */
import { act, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels, rescueSlot, type MarkReport } from "./FabricLabels";

type Box = { x: number; y: number; w: number; h: number };
type Projection = { x: number; y: number; visible: boolean };
const DEVICES = fabric.devices.slice(0, 12);
if (DEVICES.length < 12) throw new Error("A6 controls require twelve actual device identities");
const CUT = DEVICES[0]!;
const WIDTH = 150;
const HEIGHT = 16;
const originalRect = HTMLElement.prototype.getBoundingClientRect;
let frames = new Map<number, FrameRequestCallback>();
let frameId = 0;
const mounted: { root: Root; container: HTMLElement }[] = [];

const rect = (b: Box): DOMRect => ({ ...b, left: b.x, top: b.y, right: b.x + b.w,
  bottom: b.y + b.h, width: b.w, height: b.h, toJSON: () => ({}) }) as DOMRect;
const overlaps = (a: Box, b: Box): boolean => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
const whole = (b: Box, stage: { w: number; h: number }): boolean =>
  b.x >= 0 && b.y >= 0 && b.x + b.w <= stage.w && b.y + b.h <= stage.h;
function flush(n = 1): void {
  for (let i = 0; i < n; i += 1) {
    const batch = [...frames.values()];
    frames.clear();
    act(() => { for (const cb of batch) cb(0); });
  }
}

function mountStage(projections: Map<string, Projection>, options: {
  stage?: { w: number; h: number };
  report?: boolean;
  settled?: boolean;
  stranded?: readonly string[];
  obstacles?: readonly Box[];
  glyph?: Box;
} = {}) {
  const stage = options.stage ?? { w: 390, h: 320 };
  HTMLElement.prototype.getBoundingClientRect = function (): DOMRect {
    if (this.classList.contains("a6-stage") || this.classList.contains("fabric3d__labels")) return rect({ x: 0, y: 0, ...stage });
    if (this.dataset.box !== undefined) return rect(JSON.parse(this.dataset.box) as Box);
    return originalRect.call(this);
  };
  const scene = { project: (id: string) => projections.get(id) ?? null,
    labelsSettled: () => options.settled ?? false, chassisScreenBox: () => null,
    terminalGlyphScreenBox: () => options.glyph === undefined ? null : {
      host: CUT.host, x0: options.glyph.x, y0: options.glyph.y,
      x1: options.glyph.x + options.glyph.w, y1: options.glyph.y + options.glyph.h,
    } } as unknown as FabricScene;
  const sceneRef: RefObject<FabricScene | null> = { current: scene };
  let last = { outOfView: [] as readonly string[], covered: [] as readonly string[],
    metadata: null as MarkReport | null };
  const report = (outOfView: readonly string[], covered: readonly string[], metadata: MarkReport): void => {
    last = { outOfView, covered, metadata };
  };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounted.push({ root, container });
  act(() => root.render(<div className="a6-stage">
    <FabricLabels devices={DEVICES} sceneRef={sceneRef} epoch={7} hover={createHoverChannel()}
      selectedId={CUT.id} cutPointId={CUT.host} strandedIds={new Set(options.stranded ?? [])}
      {...(options.report === false ? {} : { onStrandedUnseen: report })} />
    {(options.obstacles ?? []).map((box, i) => <div key={i} data-label-keepout="" data-box={JSON.stringify(box)} />)}
  </div>));
  for (const label of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(label, "offsetWidth", { configurable: true, get: () => WIDTH });
    Object.defineProperty(label, "offsetHeight", { configurable: true, get: () => HEIGHT });
    const name = label.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => 4 });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => 72 });
  }
  const label = (id = CUT.id): HTMLElement => {
    const el = [...container.querySelectorAll<HTMLElement>(".fabric3d-label")].find((n) => n.dataset.device === id);
    if (!el) throw new Error(`A6 label missing: ${id}`);
    return el;
  };
  const drawn = (id = CUT.id): Box => {
    const transform = label(id).style.transform;
    const match = /translate3d\(([-\d.]+)px, ([-\d.]+)px, 0\) translate\(0, ([-\d.]+)%\)/.exec(transform);
    if (!match) throw new Error(`A6 placement transform missing: ${transform}`);
    return { x: Number(match[1]), y: Number(match[2]) + Number(match[3]) * HEIGHT / 100, w: WIDTH, h: HEIGHT };
  };
  return { stage, label, drawn, get report() { return last; } };
}

beforeEach(() => {
  frames = new Map(); frameId = 0;
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { const id = ++frameId; frames.set(id, cb); return id; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("MutationObserver", class { observe() {} disconnect() {} });
});
afterEach(() => {
  for (const { root, container } of mounted.splice(0)) { act(() => root.unmount()); container.remove(); }
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  vi.unstubAllGlobals();
});

describe("physical placement independent of mark reporting", () => {
  it("moves a shown cut mark wholly inside the bottom edge without any reporting callback", () => {
    const projections = new Map([[CUT.id, { x: 195, y: 160, visible: true }]]);
    const h = mountStage(projections, { report: false });
    flush(6);
    expect(h.label().dataset.visible).toBe("true");
    projections.set(CUT.id, { x: 195, y: h.stage.h + 34, visible: true });
    flush(1);
    expect(whole(h.drawn(), h.stage), "A6_PLACEMENT_PHYSICAL_BOUNDS").toBe(true);
  });
  it.each(["shown", "hidden", "settled"] as const)("bounds every physical edge for %s hysteresis without a reporter", (state) => {
    const projections = new Map([[CUT.id, { x: 195, y: 160, visible: state !== "hidden" }]]);
    const h = mountStage(projections, { report: false, settled: state === "settled",
      obstacles: [{ x: 0, y: 20, w: 390, h: 16 }] });
    flush(6);
    for (const anchor of [{ x: 195, y: -12 }, { x: -20, y: 160 }, { x: 410, y: 160 }, { x: 195, y: h.stage.h + 34 }]) {
      if (state === "hidden") { projections.set(CUT.id, { x: 195, y: 160, visible: false }); flush(1); }
      projections.set(CUT.id, { ...anchor, visible: true });
      flush(state === "settled" ? 6 : 1);
      expect(h.label().dataset.visible).toBe("true");
      expect(whole(h.drawn(), h.stage), `${state} physical edge at ${JSON.stringify(anchor)}`).toBe(true);
    }
  });
  it("keeps the terminal glyph hard when only rescue can clear stage controls", () => {
    const glyph = { x: 0, y: 180, w: 390, h: 60 };
    const h = mountStage(new Map([[CUT.id, { x: 195, y: 30, visible: true }]]), {
      report: false, glyph, obstacles: [{ x: 0, y: 0, w: 390, h: 180 }],
    });
    flush(6);
    expect(h.label().dataset.visible).toBe("true");
    expect(whole(h.drawn(), h.stage)).toBe(true);
    expect(overlaps(h.drawn(), glyph)).toBe(false);
  });
  it("does not admit physical control overlap for a shown mark's +3 hysteresis", () => {
    const control = { x: 0, y: 114, w: 390, h: 20 };
    const projections = new Map([[CUT.id, { x: 195, y: 200, visible: true }]]);
    const h = mountStage(projections, { report: false, obstacles: [control] });
    flush(6);
    expect(h.label().dataset.visible).toBe("true");
    projections.set(CUT.id, { x: 195, y: 148, visible: true }); // Actual home top100, bottom116.
    flush(1);
    expect(whole(h.drawn(), h.stage)).toBe(true);
    expect(overlaps(h.drawn(), control), "actual label ink, independent of covered flag").toBe(false);
  });
  it("does not admit physical prior-label overlap for shown marks' +3 hysteresis", () => {
    const other = DEVICES[1]!;
    const projections = new Map([[CUT.id, { x: 195, y: 260, visible: true }],
      [other.id, { x: 195, y: 140, visible: true }]]);
    const h = mountStage(projections, { report: false, stranded: [other.id] });
    flush(6);
    expect(h.label().dataset.visible).toBe("true");
    expect(h.label(other.id).dataset.visible).toBe("true");
    projections.set(CUT.id, { x: 195, y: 148, visible: true });
    flush(1);
    expect(overlaps(h.drawn(), h.drawn(other.id)), "actual boxes, independent of covered flags").toBe(false);
  });
  it("places a sixteen-pixel mark wholly on a measured seventeen-pixel stage without a reporter", () => {
    const h = mountStage(new Map([[CUT.id, { x: 195, y: 5, visible: true }]]), {
      report: false, stage: { w: 390, h: 17 },
    });
    flush(6);
    expect(h.label().dataset.visible).toBe("true");
    expect(whole(h.drawn(), h.stage)).toBe(true);
  });
});

describe("reporting independent of possible placement", () => {
  it("names a physically clipped cut mark when no whole placement can exist", () => {
    const h = mountStage(new Map([[CUT.id, { x: 195, y: 4, visible: true }]]), { stage: { w: 390, h: 8 } });
    flush(6);
    expect(h.label().dataset.visible).toBe("true");
    expect(h.drawn().h).toBeGreaterThan(h.stage.h);
    expect(whole(h.drawn(), h.stage)).toBe(false);
    expect(h.report.outOfView, "A6_REPORTING_PHYSICAL_CLIP").toEqual([CUT.id]);
    expect(h.report.covered).toEqual([]);
    expect(h.label().dataset.covered).not.toBe("yes");
    expect(h.label().dataset.clipped).toBe("yes");
  });
  it("keeps clipped and whole-covered stranded categories disjoint and accounts for every mark", () => {
    const stranded = DEVICES.slice(1).map((d) => d.id);
    const projections = new Map(stranded.map((id) => [id, { x: 195, y: 40, visible: true }]));
    projections.set(CUT.id, { x: 195, y: 140, visible: false });
    const h = mountStage(projections, { stage: { w: 390, h: 60 }, stranded });
    flush(6);
    expect(h.report.outOfView).toContain(CUT.id);
    expect(h.report.covered.length).toBeGreaterThan(0);
    expect(h.report.covered.filter((id) => h.report.outOfView.includes(id))).toEqual([]);
    for (const id of h.report.covered) {
      expect(h.label(id).dataset.visible).toBe("true");
      expect(whole(h.drawn(id), h.stage)).toBe(true);
    }
    const marked = [CUT.id, ...stranded];
    const shown = marked.filter((id) => !h.report.outOfView.includes(id) && !h.report.covered.includes(id));
    expect(new Set([...shown, ...h.report.outOfView, ...h.report.covered]).size).toBe(marked.length);
    for (const id of shown) expect(whole(h.drawn(id), h.stage)).toBe(true);
  });
  it("cannot certify whole marks on an unmeasured stage", () => {
    const h = mountStage(new Map([[CUT.id, { x: 0, y: 0, visible: true }]]), { stage: { w: 0, h: 0 } });
    flush(6);
    expect(h.report.metadata?.state).toBe("unmeasured");
    expect(h.report.outOfView).toEqual([CUT.id]);
    expect(h.report.covered).toEqual([]);
  });
});

describe("small fit and impossible-fit rescue", () => {
  it.each(["height", "width"] as const)("finds the legal clamp in a17px %s with a16px label starting at5", (axis) => {
    const stage = axis === "height" ? { w: 390, h: 17 } : { w: 17, h: 390 };
    const box = { x: 5, y: 5, w: 16, h: 16 };
    const offset = rescueSlot({ test: box, stage, anchor: { x: 8, y: 8 }, taken: () => false,
      leaderClear: () => true, readsAsOwn: () => true });
    expect(offset).not.toBeNull();
    expect(whole({ ...box, x: box.x + offset!.dx, y: box.y + offset!.dy }, stage)).toBe(true);
  });
  it.each([{ w: 390, h: 8 }, { w: 8, h: 390 }])("refuses a physically impossible stage %j", (stage) => {
    expect(rescueSlot({ test: { x: 5, y: 5, w: 16, h: 16 }, stage, anchor: { x: 8, y: 8 },
      taken: () => false, leaderClear: () => true, readsAsOwn: () => true })).toBeNull();
  });
});
