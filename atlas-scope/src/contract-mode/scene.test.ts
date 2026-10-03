import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BufferGeometry, Material, Mesh, type Camera, type Scene } from "three";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import { createContractScene, type Renderer } from "./scene";
import { completeFixture, typedPath } from "./testing";

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
function canvas(): HTMLCanvasElement {
  const viewport = document.createElement("div"), result = document.createElement("canvas");
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
    expect(document.querySelectorAll(".contract-scope-node-label")).toHaveLength(2);
    scene.path(typedPath()); expect(lineAllocations).toHaveBeenCalled();
    scene.dispose(); const allocated = lineAllocations.mock.calls.length, draws = fake.render.mock.calls.length;
    scene.dispose(); scene.path(typedPath()); scene.layer("structural_links"); scene.select(null); scene.reset(); scene.theme(); scene.render();
    expect(lineAllocations).toHaveBeenCalledTimes(allocated); expect(fake.render).toHaveBeenCalledTimes(draws);
    expect(fake.dispose).toHaveBeenCalledTimes(1); expect(fake.forceContextLoss).toHaveBeenCalledTimes(1); expect(disconnect).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith("click", expect.any(Function)); expect(remove).toHaveBeenCalledWith("webglcontextlost", expect.any(Function));
    expect(frames.size).toBe(0); expect(failed).not.toHaveBeenCalled(); expect(document.querySelector(".contract-scope-labels")).toBeNull();
  });

  it("turns context loss into one parent fallback after disposal", async () => {
    const model = await completeFixture(), target = canvas(), fake = renderer(target), failed = vi.fn();
    const scene = createContractScene(target, model, { makeRenderer: () => fake, onSelect: vi.fn(), onFailure: failed });
    const event = new Event("webglcontextlost", { cancelable: true }); target.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true); expect(failed).toHaveBeenCalledTimes(1); expect(fake.dispose).toHaveBeenCalledTimes(1);
    target.dispatchEvent(new Event("webglcontextlost")); scene.dispose(); expect(failed).toHaveBeenCalledTimes(1);
  });
});
