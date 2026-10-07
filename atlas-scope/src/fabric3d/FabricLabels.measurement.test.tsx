/** Measurement availability only: the scene and layout dimensions below are synthetic controls. */
import { act, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels, strandedMeasurementScope, type StrandedMeasurement } from "./FabricLabels";

const DEVICES = fabric.devices.slice(0, 2);
if (DEVICES.length !== 2) throw new Error("Measurement controls require two device identities");
const CUT = DEVICES[0]!;
const STRANDED = DEVICES[1]!;
const originalRect = HTMLElement.prototype.getBoundingClientRect;
let frames = new Map<number, FrameRequestCallback>();
let frameId = 0;
const mounted: { root: Root; container: HTMLElement }[] = [];
const observers: { callback: ResizeObserverCallback; targets: Set<Element> }[] = [];
const rect = (width: number, height: number): DOMRect => ({ x: 0, y: 0, left: 0, top: 0,
  right: width, bottom: height, width, height, toJSON: () => ({}) }) as DOMRect;

function flush(count = 1): void {
  for (let i = 0; i < count; i += 1) {
    const callbacks = [...frames.values()]; frames.clear();
    act(() => { for (const callback of callbacks) callback(0); });
  }
}

function mount(stage = { width: 500, height: 320 }, dimensions = { width: 150, height: 16 }) {
  const container = document.createElement("div"); document.body.appendChild(container);
  const root = createRoot(container); mounted.push({ root, container });
  let labelSize = dimensions;
  let currentStage = stage;
  const projections = new Map([
    [CUT.id, { x: 90, y: 120, visible: true }],
    [STRANDED.id, { x: 350, y: 220, visible: true }],
  ]);
  const scene = { project: (id: string) => projections.get(id) ?? null,
    labelsSettled: () => false, chassisScreenBox: () => null } as unknown as FabricScene;
  const sceneRef: RefObject<FabricScene | null> = { current: scene };
  const reports: { unseen: readonly string[]; measurement: StrandedMeasurement }[] = [];
  HTMLElement.prototype.getBoundingClientRect = function (): DOMRect {
    return this.classList.contains("fabric3d__labels") ? rect(currentStage.width, currentStage.height) : originalRect.call(this);
  };
  act(() => {
    root.render(<FabricLabels devices={DEVICES} sceneRef={sceneRef} epoch={7}
      hover={createHoverChannel()} selectedId={null} cutPointId={CUT.host} strandedIds={new Set([STRANDED.id])}
      onStrandedUnseen={(unseen, measurement) => { reports.push({ unseen, measurement }); }} />);
  });
  const overlay = container.querySelector<HTMLElement>(".fabric3d__labels")!;
  for (const label of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(label, "offsetWidth", { configurable: true, get: () => labelSize.width });
    Object.defineProperty(label, "offsetHeight", { configurable: true, get: () => labelSize.height });
    const name = label.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => 4 });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => 72 });
  }
  return {
    reports, projections,
    last: () => { const report = reports.at(-1); if (!report) throw new Error("Missing measurement report"); return report; },
    setSize: (value: typeof dimensions): void => { labelSize = value; },
    setStage: (value: typeof stage): void => {
      currentStage = value;
      act(() => {
        for (const observer of observers) if (observer.targets.has(overlay)) {
          observer.callback([{ target: overlay, borderBoxSize: [], contentRect: rect(value.width, value.height) } as unknown as ResizeObserverEntry], {} as ResizeObserver);
        }
      });
    },
  };
}

beforeEach(() => {
  frames = new Map(); frameId = 0; observers.length = 0;
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { const id = ++frameId; frames.set(id, callback); return id; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("ResizeObserver", class {
    entry: (typeof observers)[number];
    constructor(callback: ResizeObserverCallback) { this.entry = { callback, targets: new Set() }; observers.push(this.entry); }
    observe(target: Element): void { this.entry.targets.add(target); }
    unobserve(target: Element): void { this.entry.targets.delete(target); }
    disconnect(): void { this.entry.targets.clear(); }
  });
  vi.stubGlobal("MutationObserver", class { observe() {} disconnect() {} });
});
afterEach(() => {
  for (const { root, container } of mounted.splice(0)) { act(() => { root.unmount(); }); container.remove(); }
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  vi.unstubAllGlobals();
});

describe("unseen counts require current measured stage and visible label boxes", () => {
  it.each([{ width: 0, height: 320 }, { width: 500, height: 0 }])("withholds zero stage bounds %j and recovers after actual measurement", (stage) => {
    const h = mount(stage);
    expect(h.last().measurement.state).toBe("unmeasured");
    flush(4);
    expect(h.last().measurement.state).toBe("unmeasured");
    h.setStage({ width: 500, height: 320 }); flush(4);
    expect(h.last().measurement.state).toBe("measured");
    expect(h.last().unseen).toEqual([]);
    expect(h.last().measurement.source).toBe(DEVICES);
    expect(h.last().measurement.epoch).toBe(7);
    expect(h.last().measurement.scope).toBe(strandedMeasurementScope(CUT.id, [STRANDED.id], ""));
  });
  it.each([{ width: 0, height: 16 }, { width: 150, height: 0 }])("does not cache an incomplete visible label box %j as measured", (size) => {
    const h = mount(undefined, size); flush(4);
    expect(h.last().measurement.state).toBe("unmeasured");
    h.setSize({ width: 150, height: 16 }); flush(4);
    expect(h.last().measurement.state).toBe("measured");
    expect(h.last().unseen).toEqual([]);
  });
  it("keeps measured main visibility semantics during motion and accounts for hidden labels", () => {
    const h = mount(); flush(4);
    expect(h.last().measurement.state).toBe("measured");
    h.projections.set(STRANDED.id, { x: 340, y: 210, visible: true }); flush(1);
    expect(h.last().measurement.state).toBe("measured");
    h.projections.set(STRANDED.id, { x: 340, y: 210, visible: false }); flush(1);
    expect(h.last().measurement.state).toBe("measured");
    expect(h.last().unseen).toEqual([STRANDED.id]);
  });
  it("invalidates a collapsed stage and does not republish identical unmeasured frames", () => {
    const h = mount(); flush(4);
    expect(h.last().measurement.state).toBe("measured");
    h.setStage({ width: 0, height: 0 }); flush(4);
    expect(h.last().measurement.state).toBe("unmeasured");
    const before = h.reports.length; flush(4);
    expect(h.reports.length).toBe(before);
    h.setStage({ width: 500, height: 320 }); flush(4);
    expect(h.last().measurement.state).toBe("measured");
  });
});
