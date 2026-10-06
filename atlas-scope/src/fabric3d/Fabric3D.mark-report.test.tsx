/** Parent wiring controls use synthetic report input, independently of placement tests. */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { FabricScene } from "./contract";
import type { FabricLabelsProps, MarkReport } from "./FabricLabels";
import { markReportScope } from "./FabricLabels";
import { BlastMarkNote, Fabric3D } from "./Fabric3D";

const mock = vi.hoisted(() => ({ labels: null as FabricLabelsProps | null }));
vi.mock("../core/data", async (original) => {
  const data = await original<typeof import("../core/data")>();
  const devices = data.fabric.devices.filter((d) => d.collected).slice(0, 5)
    .map((d, i) => ({ ...d, id: `a6-device-${i}` }));
  if (devices.length !== 5) throw new Error("A6 wiring controls require five collected device records");
  return { ...data, fabric: { ...data.fabric, devices, links: [], findings: [] },
    deviceById: new Map(devices.flatMap((d) => [[d.id, d], [d.host, d]] as const)),
    linkById: new Map(), linksByHost: new Map(), findingsByHost: new Map() };
});
vi.mock("../analysis/blast", async (original) => {
  const data = await import("../core/data");
  const actual = await original<typeof import("../analysis/blast")>();
  return { ...actual, failureImpact: (host: string) => ({
    newlyStranded: host === data.fabric.devices[0]!.host
      ? [data.fabric.devices[1]!.host, data.fabric.devices[2]!.host]
      : host === data.fabric.devices[1]!.host ? [data.fabric.devices[0]!.host, data.fabric.devices[2]!.host]
        : host === data.fabric.devices[3]!.host ? [data.fabric.devices[1]!.host, "synthetic-unresolved-host"] : [],
    certainty: "observed", alternateProjections: [], caveats: [],
  }) };
});
vi.mock("./FabricLabels", async (original) => {
  const actual = await original<typeof import("./FabricLabels")>();
  return { ...actual, FabricLabels: (props: FabricLabelsProps) => { mock.labels = props; return null; } };
});
vi.mock("./materials", async (original) => ({ ...(await original<typeof import("./materials")>()),
  proceduralMapsReady: () => true, prepareProceduralMaps: async () => undefined }));
vi.mock("./geometry/chassis", async (original) => ({ ...(await original<typeof import("./geometry/chassis")>()),
  chassisPrepared: () => true, prepareChassis: async () => undefined }));
vi.mock("./scene", () => ({ createScene: () => ({
  setData() {}, setSelection() {}, setHover() {}, setHighlight() {}, setTrace() {}, focusDevice() {},
  resetCamera() {}, setTheme() {}, setQuality() {}, resize() {}, dispose() {}, setReducedMotion() {},
  pick: () => null, project: () => null,
  stats: () => ({ fps: 60, frameMs: 16, triangles: 0, programs: 0, converged: true,
    quality: "high", drawCalls: 0, drawCallBudget: 88, activeOutlines: 0, overBudget: false,
    worstFrameMs: 16, qualityReasons: [], qualityAuto: true, missingTokens: [], undrawnHops: [],
    labelsShown: 0, labelsTotal: 5 }),
}) as unknown as FabricScene }));

const roots: { root: Root; container: HTMLElement }[] = [];
let frames = new Map<number, FrameRequestCallback>();
let frameId = 0;
const originalRect = HTMLElement.prototype.getBoundingClientRect;
function mount(element: ReactNode): HTMLElement {
  const container = document.createElement("div"); document.body.appendChild(container);
  const root = createRoot(container); roots.push({ root, container });
  act(() => root.render(element));
  return container;
}
function labels(): FabricLabelsProps {
  if (mock.labels === null) throw new Error("actual Fabric3D did not wire its label layer");
  return mock.labels;
}
function metadata(state: MarkReport["state"]): MarkReport {
  const props = labels();
  const cut = props.devices.find((d) => d.host === props.cutPointId || d.id === props.cutPointId)?.id;
  return { ids: [...new Set([...(props.strandedIds ?? []), ...(cut === undefined ? [] : [cut])])].sort(),
    scope: markReportScope(cut ?? null, props.strandedIds ?? [], props.strandedQualifier ?? ""), epoch: props.epoch, state };
}
function report(outOfView: readonly string[], covered: readonly string[], state: MarkReport["state"] = "ready", supplied = metadata(state)): void {
  const callback = labels().onStrandedUnseen;
  if (!callback) throw new Error("actual Fabric3D did not install the report callback");
  act(() => callback(outOfView, covered, supplied));
}
beforeEach(() => {
  mock.labels = null; frames = new Map(); frameId = 0;
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { const id = ++frameId; frames.set(id, cb); return id; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  HTMLElement.prototype.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, right: 1200,
    bottom: 800, width: 1200, height: 800, toJSON: () => ({}) }) as DOMRect;
  useInvestigation.getState().reset();
});
afterEach(() => {
  for (const { root, container } of roots.splice(0)) { act(() => root.unmount()); container.remove(); }
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  vi.unstubAllGlobals(); useInvestigation.getState().reset();
});

describe("actual Fabric3D report wiring", () => {
  it("names disjoint out-of-view and covered hosts, preserving cut-ID normalization and exact counts", () => {
    const [cut, off, covered] = fabric.devices;
    expect(cut!.id).not.toBe(cut!.host);
    const container = mount(<Fabric3D />);
    act(() => useInvestigation.getState().selectDevice(cut!.id));
    expect(labels().cutPointId).toBe(cut!.host);
    const before = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(before.dataset.markReport).toBe("pending");
    expect(before.textContent).not.toMatch(/all \d+ marked/);
    report([off!.id, cut!.id], [covered!.id]);
    const note = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(note.dataset.markReport).toBe("ready");
    expect(note.dataset.strandedTotal).toBe("2");
    expect(note.dataset.strandedShown).toBe("0");
    expect(note.dataset.strandedOutOfView).toBe("1");
    expect(note.dataset.strandedCovered).toBe("1");
    expect(note.dataset.cutMark).toBe("out-of-view");
    expect(note.textContent).toContain(`1 out of view: ${off!.host}`);
    expect(note.textContent).toContain(`1 covered: ${covered!.host}`);
    expect(note.textContent).not.toContain(off!.id);
  });
  it("refuses a previous selection report and withholds whole counts until the current report arrives", () => {
    const [cut, next] = fabric.devices;
    const container = mount(<Fabric3D />);
    act(() => useInvestigation.getState().selectDevice(cut!.id));
    const previous = metadata("ready");
    report([], []);
    expect(container.querySelector("[data-stranded-total]")!.textContent).toContain("all 2 marked");
    act(() => useInvestigation.getState().selectDevice(next!.id));
    expect(metadata("ready").ids).toEqual(previous.ids); // Same union, different cut/stranded roles.
    report([], [], "ready", previous);
    const pending = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(pending.dataset.markReport).toBe("pending");
    expect(pending.dataset.cutMark).toBe("pending");
    expect(pending.hasAttribute("data-stranded-shown")).toBe(false);
    expect(pending.textContent).not.toContain("all 2 marked");
    report([], []);
    expect(container.querySelector<HTMLElement>("[data-stranded-total]")!.dataset.strandedShown).toBe("2");
    report([], [], "unmeasured");
    const unknown = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(unknown.dataset.markReport).toBe("unmeasured");
    expect(unknown.dataset.cutMark).toBe("unmeasured");
    expect(unknown.textContent).not.toMatch(/all \d+ marked/);
  });
  it("does not invent a cut-point overlay for a genuinely zero-impact selection", () => {
    const container = mount(<Fabric3D />);
    act(() => useInvestigation.getState().selectDevice(fabric.devices[4]!.id));
    expect(labels().cutPointId).toBeNull();
    expect(container.querySelector("[data-stranded-total]")).toBeNull();
  });
  it("refuses an epoch-only stale report even when its mark roles are unchanged", () => {
    const container = mount(<Fabric3D />);
    act(() => useInvestigation.getState().selectDevice(fabric.devices[0]!.id));
    const old = { ...metadata("ready"), epoch: labels().epoch - 1 };
    report([], [], "ready", old);
    const note = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(note.dataset.markReport).toBe("pending");
    expect(note.hasAttribute("data-stranded-shown")).toBe(false);
  });
  it("names an unresolved stranded host as not drawn rather than certifying all resolved labels", () => {
    const container = mount(<Fabric3D />);
    act(() => useInvestigation.getState().selectDevice(fabric.devices[3]!.id));
    report([], []);
    const note = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(note.dataset.strandedTotal).toBe("2");
    expect(note.dataset.strandedShown).toBe("1");
    expect(note.dataset.strandedOutOfView).toBe("1");
    expect(note.textContent).toContain("synthetic-unresolved-host");
    expect(note.textContent).not.toContain("all 2 marked");
  });
  it("gives out-of-view precedence over overlapping callback categories without double counting", () => {
    const container = mount(<Fabric3D />);
    act(() => useInvestigation.getState().selectDevice(fabric.devices[0]!.id));
    const [cut, off, covered] = fabric.devices;
    report([cut!.id, off!.id], [cut!.id, off!.id, covered!.id]);
    const note = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(note.dataset.strandedUnseen).toBe("2");
    expect(note.dataset.strandedOutOfView).toBe("1");
    expect(note.dataset.strandedCovered).toBe("1");
    expect(note.dataset.cutMark).toBe("out-of-view");
    expect(JSON.parse(note.dataset.strandedOutOfViewHosts!)).toEqual([off!.host]);
    expect(JSON.parse(note.dataset.strandedCoveredHosts!)).toEqual([covered!.host]);
  });
});

describe("cut-only HUD boundary", () => {
  it("does not certify all-zero marks or a shown cut point before its report", () => {
    const container = mount(<BlastMarkNote subject="synthetic cut" qualifier="" certainty="observed"
      strandedHosts={[]} outOfView={[]} covered={[]} cutHost="synthetic cut" cutState="shown" state="pending" />);
    const note = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(note.dataset.cutMark).toBe("pending");
    expect(note.hasAttribute("data-stranded-shown")).toBe(false);
    expect(note.textContent).not.toContain("all 0 marked");
    expect(note.textContent).not.toContain("cut-point mark shown");
  });
  it("states a cut-only covered mark without calling it shown or certifying a stranded set", () => {
    const container = mount(<BlastMarkNote subject="synthetic cut" qualifier="" certainty="observed"
      strandedHosts={[]} outOfView={[]} covered={[]} cutHost="synthetic cut" cutState="covered" state="ready" />);
    const note = container.querySelector<HTMLElement>("[data-stranded-total]")!;
    expect(note.dataset.cutMark).toBe("covered");
    expect(note.textContent).toContain("cut-point mark covered");
    expect(note.textContent).not.toContain("all 0 marked");
  });
});
