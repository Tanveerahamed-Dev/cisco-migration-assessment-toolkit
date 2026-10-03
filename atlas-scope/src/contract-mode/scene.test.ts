import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Box3, BufferGeometry, InstancedMesh, Material, Mesh, PerspectiveCamera, Raycaster, Vector3, type Camera, type Scene } from "three";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import { createContractScene, type Renderer } from "./scene";
import { completeFixture, typedPath } from "../test-support/projection-contract-fixtures";

const variables = ["--bg", "--text", "--text-muted", "--unobserved-edge", "--accent", "--sev-medium", "--sev-critical"];
let saved: string[] = [];
let frame = 0;
const frames = new Map<number, FrameRequestCallback>();
const disconnect = vi.fn();
beforeEach(() => {
  saved = variables.map((key) => document.documentElement.style.getPropertyValue(key));
  variables.forEach((key) => document.documentElement.style.setProperty(key, "rgb(20, 30, 40)"));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++frame, callback); return frame; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void { disconnect(); } });
});
afterEach(() => {
  variables.forEach((key, index) => { if (saved[index]) document.documentElement.style.setProperty(key, saved[index]!); else document.documentElement.style.removeProperty(key); });
  frames.clear(); disconnect.mockClear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.replaceChildren();
});
function renderer(canvas: HTMLCanvasElement): Renderer & { render: ReturnType<typeof vi.fn<(scene: Scene, camera: Camera) => void>> } {
  return { domElement: canvas, setSize: vi.fn(), setPixelRatio: vi.fn(), render: vi.fn<(scene: Scene, camera: Camera) => void>(),
    dispose: vi.fn(), forceContextLoss: vi.fn() };
}
function canvas(width = 800, height = 450): HTMLCanvasElement {
  const viewport = document.createElement("div"), result = document.createElement("canvas");
  Object.defineProperties(result, { clientWidth: { value: width, configurable: true }, clientHeight: { value: height, configurable: true } });
  vi.spyOn(result, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, width, height));
  viewport.append(result); document.body.append(viewport); return result;
}

describe("contract renderer resource ownership", () => {
  it("refuses unavailable WebGL without installing a scene", async () => {
    const model = await completeFixture(), target = canvas();
    expect(() => createContractScene(target, model, { makeRenderer: () => { throw new Error("private graphics detail"); },
      onSelect: vi.fn(), onFailure: vi.fn() })).toThrow("WEBGL_UNAVAILABLE");
    expect(document.querySelector(".contract-scope-labels")).toBeNull();
    expect(frames.size).toBe(0);
  });

  it("stops initialization on the first render failure and frees every allocated resource", async () => {
    const model = await completeFixture(), target = canvas(), fake = renderer(target);
    const lineAllocations = vi.spyOn(LineSegmentsGeometry.prototype, "setPositions");
    const observedGeometry = new Set<BufferGeometry>(), observedMaterial = new Set<Material>();
    const freedGeometry = new Set<BufferGeometry>(), freedMaterial = new Set<Material>();
    fake.render.mockImplementation((scene) => {
      scene.traverse((object) => {
        if (!(object instanceof Mesh)) return;
        observedGeometry.add(object.geometry); object.geometry.addEventListener("dispose", () => freedGeometry.add(object.geometry));
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
          observedMaterial.add(material); material.addEventListener("dispose", () => freedMaterial.add(material));
        }
      });
      throw new Error("synthetic first draw failure");
    });
    expect(() => createContractScene(target, model, { makeRenderer: () => fake, onSelect: vi.fn(), onFailure: vi.fn() })).toThrow("RENDER_FAILED");
    expect(observedGeometry.size).toBeGreaterThan(0);
    expect(freedGeometry).toEqual(observedGeometry); expect(freedMaterial).toEqual(observedMaterial);
    expect(lineAllocations).not.toHaveBeenCalled(); // No theme/drawLinks construction after disposal.
    expect(fake.render).toHaveBeenCalledTimes(1); expect(fake.dispose).toHaveBeenCalledTimes(1); expect(fake.forceContextLoss).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".contract-scope-labels")).toBeNull(); expect(frames.size).toBe(0);
  });

  it("disposes GPU objects, observer, animation and listeners once; later updates allocate nothing", async () => {
    const model = await completeFixture(), target = canvas(), fake = renderer(target), failed = vi.fn();
    const remove = vi.spyOn(target, "removeEventListener"), lineAllocations = vi.spyOn(LineSegmentsGeometry.prototype, "setPositions");
    const scene = createContractScene(target, model, { makeRenderer: () => fake, onSelect: vi.fn(), onFailure: failed });
    expect(document.querySelectorAll(".contract-scope-node-label")).toHaveLength(0);
    scene.path(typedPath()); expect(lineAllocations).toHaveBeenCalled();
    scene.dispose(); const allocated = lineAllocations.mock.calls.length, draws = fake.render.mock.calls.length;
    scene.dispose(); scene.path(typedPath()); scene.layer("structural_links"); scene.select(null); scene.reset(); scene.theme(); scene.render();
    expect(lineAllocations).toHaveBeenCalledTimes(allocated); expect(fake.render).toHaveBeenCalledTimes(draws);
    expect(fake.dispose).toHaveBeenCalledTimes(1); expect(fake.forceContextLoss).toHaveBeenCalledTimes(1); expect(disconnect).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith("click", expect.any(Function)); expect(remove).toHaveBeenCalledWith("webglcontextlost", expect.any(Function));
    expect(remove).toHaveBeenCalledWith("pointermove", expect.any(Function)); expect(remove).toHaveBeenCalledWith("pointerleave", expect.any(Function));
    expect(frames.size).toBe(0); expect(failed).not.toHaveBeenCalled(); expect(document.querySelector(".contract-scope-labels")).toBeNull();
  });

  it("turns context loss into one parent fallback after disposal", async () => {
    const model = await completeFixture(), target = canvas(), fake = renderer(target), failed = vi.fn();
    const scene = createContractScene(target, model, { makeRenderer: () => fake, onSelect: vi.fn(), onFailure: failed });
    const event = new Event("webglcontextlost", { cancelable: true }); target.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true); expect(failed).toHaveBeenCalledTimes(1); expect(fake.dispose).toHaveBeenCalledTimes(1);
    target.dispatchEvent(new Event("webglcontextlost")); scene.dispose(); expect(failed).toHaveBeenCalledTimes(1);
  });

  it.each([{ width: 1072, height: 370 }, { width: 282, height: 257 }])("fits all display geometry into a $width by $height viewport", async ({ width, height }) => {
    const model = await completeFixture();
    const nodes = Array.from({ length: 26 }, (_, index) => ({ ...model.rows.nodes[0]!, index, pointer: `/cable_map/nodes/${index}` }));
    const expanded = { ...model, rows: { ...model.rows, nodes } }, source = JSON.stringify(expanded);
    const target = canvas(width, height), fake = renderer(target);
    const view = createContractScene(target, expanded, { makeRenderer: () => fake, onSelect: vi.fn(), onFailure: vi.fn() });
    const [scene, camera] = fake.render.mock.calls.at(-1)!;
    expect(camera).toBeInstanceOf(PerspectiveCamera); expect((camera as PerspectiveCamera).aspect).toBe(width / height);
    scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
    const bounds = new Box3().setFromObject(scene), points: Vector3[] = [];
    for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
      points.push(new Vector3(x, y, z).project(camera));
    }
    expect(points.every((point) => Math.abs(point.x) <= 0.9 && Math.abs(point.y) <= 0.9 && point.z > -1 && point.z < 1)).toBe(true);
    const coverage = Math.max((Math.max(...points.map(p => p.x)) - Math.min(...points.map(p => p.x))) / 2,
      (Math.max(...points.map(p => p.y)) - Math.min(...points.map(p => p.y))) / 2);
    expect(coverage).toBeGreaterThan(0.6);
    expect(JSON.stringify(expanded)).toBe(source);
    view.dispose();
  });

  it("shows at most one hover-or-selected label without changing selection or record data", async () => {
    const model = await completeFixture(), source = JSON.stringify(model), target = canvas(), fake = renderer(target), selected = vi.fn();
    const view = createContractScene(target, model, { makeRenderer: () => fake, onSelect: selected, onFailure: vi.fn() });
    const visible = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>(".contract-scope-node-label")].filter(element => element.style.display !== "none");
    expect(visible()).toHaveLength(0);
    const first = model.rows.nodes[0]!, second = model.rows.nodes[1]!;
    const name = (row: typeof first) => row.host.state === "published" ? row.host.value : row.host.state;
    view.select({ list: "nodes", row: { index: second.index, pointer: second.pointer } });
    expect(visible()).toHaveLength(1); expect(visible()[0]!.textContent).toBe(name(second));
    let mesh: InstancedMesh | undefined;
    fake.render.mock.calls.at(-1)![0].traverse(object => { if (!mesh && object instanceof InstancedMesh) mesh = object; });
    expect(mesh).toBeDefined();
    vi.spyOn(Raycaster.prototype, "intersectObjects").mockReturnValue([{ distance: 1, point: new Vector3(), object: mesh!, instanceId: 0 }]);
    target.dispatchEvent(new MouseEvent("pointermove", { clientX: 400, clientY: 225, buttons: 0 })); view.render();
    expect(visible()).toHaveLength(1); expect(visible()[0]!.textContent).toBe(name(first));
    target.dispatchEvent(new Event("pointerleave")); view.render();
    expect(visible()).toHaveLength(1); expect(visible()[0]!.textContent).toBe(name(second));
    expect(selected).not.toHaveBeenCalled(); expect(JSON.stringify(model)).toBe(source);
    view.select(null); expect(visible()).toHaveLength(0);
    view.dispose(); expect(document.querySelector(".contract-scope-node-label")).toBeNull();
  });

  it("refits a resized untouched view, preserves user zoom, and makes Reset restore automatic fitting", async () => {
    const model = await completeFixture(), target = canvas(), fake = renderer(target);
    const view = createContractScene(target, model, { makeRenderer: () => fake, onSelect: vi.fn(), onFailure: vi.fn() });
    const camera = fake.render.mock.calls.at(-1)![1] as PerspectiveCamera;
    const resize = (width: number, height: number): void => {
      Object.defineProperties(target, { clientWidth: { value: width, configurable: true }, clientHeight: { value: height, configurable: true } });
      window.dispatchEvent(new Event("resize")); view.render();
    };
    const initial = camera.position.clone();
    resize(300, 600);
    expect(camera.aspect).toBe(0.5); expect(camera.position.equals(initial)).toBe(false);
    const fitted = camera.position.clone();
    target.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, clientX: 150, clientY: 300, cancelable: true }));
    expect(camera.position.equals(fitted)).toBe(false);
    const userView = camera.position.clone();
    resize(1000, 300);
    expect(camera.aspect).toBe(1000 / 300); expect(camera.position.equals(userView)).toBe(true);
    view.reset(); const reset = camera.position.clone();
    expect(reset.equals(userView)).toBe(false);
    resize(400, 600);
    expect(camera.aspect).toBe(400 / 600); expect(camera.position.equals(reset)).toBe(false);
    view.dispose();
  });
});
