/** Synthetic parent-report wiring only; not label geometry, rendering or scene-convergence proof. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { FabricScene } from "./contract";
import { strandedMeasurementScope, type FabricLabelsProps, type StrandedMeasurement } from "./FabricLabels";
import { Fabric3D } from "./Fabric3D";

const mock = vi.hoisted(() => ({ labels: null as FabricLabelsProps | null }));
vi.mock("../core/data", async (original) => {
  const data = await original<typeof import("../core/data")>();
  const devices = data.fabric.devices.filter((d) => d.collected).slice(0, 3)
    .map((d, i) => ({ ...d, id: `measurement-device-${i}` }));
  if (devices.length !== 3) throw new Error("Measurement wiring needs three collected device records");
  return { ...data, fabric: { ...data.fabric, devices, links: [], findings: [] },
    deviceById: new Map(devices.flatMap((d) => [[d.id, d], [d.host, d]] as const)),
    linkById: new Map(), linksByHost: new Map(), findingsByHost: new Map() };
});
vi.mock("../analysis/blast", async (original) => {
  const data = await import("../core/data");
  return { ...(await original<typeof import("../analysis/blast")>()), failureImpact: (host: string) => ({
    newlyStranded: host === data.fabric.devices[0]!.host ? [data.fabric.devices[1]!.host, data.fabric.devices[2]!.host] : [],
    certainty: "observed", alternateProjections: [], caveats: [],
  }) };
});
vi.mock("./FabricLabels", async (original) => ({ ...(await original<typeof import("./FabricLabels")>()),
  FabricLabels: (props: FabricLabelsProps) => { mock.labels = props; return null; } }));
vi.mock("./materials", async (original) => ({ ...(await original<typeof import("./materials")>()),
  proceduralMapsReady: () => true, prepareProceduralMaps: async () => undefined }));
vi.mock("./geometry/chassis", async (original) => ({ ...(await original<typeof import("./geometry/chassis")>()),
  chassisPrepared: () => true, prepareChassis: async () => undefined }));
vi.mock("./scene", () => ({ createScene: () => ({
  setData() {}, setSelection() {}, setHover() {}, setHighlight() {}, setTrace() {}, focusDevice() {},
  resetCamera() {}, setTheme() {}, setQuality() {}, resize() {}, dispose() {}, setReducedMotion() {},
  pick: () => null, project: () => null,
  stats: () => ({ fps: 60, frameMs: 16, triangles: 0, programs: 0, converged: true, quality: "high",
    drawCalls: 0, drawCallBudget: 88, activeOutlines: 0, overBudget: false, worstFrameMs: 16,
    qualityReasons: [], qualityAuto: true, missingTokens: [], undrawnHops: [], labelsShown: 0, labelsTotal: 3 }),
}) as unknown as FabricScene }));

let root: Root | null = null;
let container: HTMLElement | null = null;
const originalRect = HTMLElement.prototype.getBoundingClientRect;
function labels(): FabricLabelsProps {
  if (!mock.labels) throw new Error("Actual parent did not wire the label reporter");
  return mock.labels;
}
function measurement(state: StrandedMeasurement["state"]): StrandedMeasurement {
  const props = labels();
  const cut = props.devices.find((d) => d.id === props.cutPointId || d.host === props.cutPointId)?.id ?? null;
  return { state, source: props.devices, epoch: props.epoch,
    scope: strandedMeasurementScope(cut, props.strandedIds ?? [], props.strandedQualifier ?? "") };
}
function report(state: StrandedMeasurement["state"], unseen: readonly string[] = [], supplied = measurement(state)): void {
  const callback = labels().onStrandedUnseen;
  if (!callback) throw new Error("Actual parent did not install the callback");
  act(() => { callback(unseen, supplied); });
}
function note(): HTMLElement {
  const element = container?.querySelector<HTMLElement>("[data-stranded-total]");
  if (!element) throw new Error("Positive source radius needs a reporting HUD");
  return element;
}
beforeEach(() => {
  mock.labels = null;
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("requestAnimationFrame", () => 1);
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  HTMLElement.prototype.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, right: 1200,
    bottom: 800, width: 1200, height: 800, toJSON: () => ({}) }) as DOMRect;
  useInvestigation.getState().reset();
  container = document.createElement("div"); document.body.appendChild(container);
  root = createRoot(container);
  act(() => { root!.render(<Fabric3D />); });
  // This three-device, prepared-assets fixture takes the synchronous layout/scene path.
  expect(container.querySelector<HTMLElement>(".fabric3d")?.dataset.layout).toBe("ready");
  expect(labels().sceneRef.current).not.toBeNull();
  act(() => { useInvestigation.getState().selectDevice(fabric.devices[0]!.id); });
});
afterEach(() => {
  if (root) act(() => { root!.unmount(); });
  container?.remove(); root = null; container = null;
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  vi.unstubAllGlobals(); useInvestigation.getState().reset();
});

describe("the existing stranded HUD withholds unmeasured visibility", () => {
  it("never treats the initial absent report as zero unseen, then recovers with a measured report", () => {
    expect(note().dataset.markMeasurement).toBe("unmeasured");
    expect(note().hasAttribute("data-stranded-unseen")).toBe(false);
    expect(note().textContent).not.toContain("all 2 marked");
    report("unmeasured");
    expect(note().textContent).toContain("visibility unmeasured");
    report("measured");
    expect(note().dataset.markMeasurement).toBe("measured");
    expect(note().dataset.strandedUnseen).toBe("0");
    expect(note().textContent).toContain("all 2 marked");
    report("measured", [fabric.devices[1]!.id]);
    expect(note().dataset.strandedUnseen).toBe("1");
    expect(note().textContent).toContain(`out of view: ${fabric.devices[1]!.host}`);
    report("unmeasured");
    expect(note().hasAttribute("data-stranded-unseen")).toBe(false);
    expect(note().textContent).not.toContain("all 2 marked");
  });
  it.each(["source", "epoch", "scope"] as const)("rejects a stale %s measurement without losing positive current recovery", (field) => {
    const stale = measurement("measured");
    if (field === "source") stale.source = [...stale.source];
    else if (field === "epoch") stale.epoch -= 1;
    else stale.scope = strandedMeasurementScope(null, [], "another subject");
    report("measured", [], stale);
    expect(note().dataset.markMeasurement).toBe("unmeasured");
    expect(note().hasAttribute("data-stranded-unseen")).toBe(false);
    expect(note().textContent).not.toContain("all 2 marked");
    report("measured");
    expect(note().textContent).toContain("all 2 marked");
  });
});
