/**
 * FabricLabels.settled.test.tsx — the DOM declutter settles to a pure function of the final pose.
 *
 * Independent critic, acceptance F6 (2026-09-22): the label layer's hysteresis reads each label's
 * previous `data-visible`, and its staggered drops count frames, so which names survive on a still
 * camera depended on the frames that led there — `access8` kept on 7 of 10 fresh loads of the same
 * state and dropped on 3, every settle condition met both times. These tests reach ONE final
 * projection along different paths and require the same visible set, and also show that while the
 * camera is still moving (the scene says it is not settled) the history does apply, so the settled
 * pass is not a test of nothing.
 */
import { act, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels } from "./FabricLabels";

type P = { x: number; y: number; visible: boolean };

const [A, B, C] = fabric.devices.slice(0, 3) as [Device, Device, Device];
const DEVICES: Device[] = [A, B, C];

/* Every label is 100 x 16 with its name centred, so a label's box is [x - 50, x + 50]. */
const W = 100;
const H = 16;

let frames = new Map<number, FrameRequestCallback>();
let nextId = 1;
const flush = (n = 1): void => {
  for (let i = 0; i < n; i += 1) {
    const batch = [...frames.values()];
    frames = new Map();
    for (const cb of batch) cb(0);
  }
};

interface Harness {
  proj: Map<string, P>;
  sceneSettled: { value: boolean | undefined };
  visible(): string[];
  unmount(): void;
}

function mountLabels(): Harness {
  const proj = new Map<string, P>();
  const sceneSettled: { value: boolean | undefined } = { value: undefined };
  const scene = {
    project: (id: string) => proj.get(id) ?? null,
  } as unknown as FabricScene;
  Object.defineProperty(scene, "labelsSettled", {
    get: () => (sceneSettled.value === undefined ? undefined : () => sceneSettled.value === true),
  });
  const ref: RefObject<FabricScene | null> = { current: scene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  act(() => {
    root.render(
      <FabricLabels devices={DEVICES} sceneRef={ref} epoch={0} hover={createHoverChannel()} selectedId={null} />,
    );
  });
  const overlay = container.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]');
  if (overlay === null) throw new Error("no overlay");
  overlay.getBoundingClientRect = (): DOMRect =>
    ({ left: 0, top: 0, right: 2000, bottom: 1000, width: 2000, height: 1000, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  for (const el of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => W });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => H });
    const name = el.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => 20 });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => 60 });
  }
  return {
    proj,
    sceneSettled,
    visible: () =>
      [...container.querySelectorAll<HTMLElement>(".fabric3d-label")]
        .filter((e) => e.dataset.visible === "true")
        .map((e) => e.dataset.device ?? "")
        .sort(),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/** Place the three anchors: A fixed, B at `bx`, C far away. All on one row. */
const pose = (h: Harness, bx: number): void => {
  h.proj.set(A.id, { x: 300, y: 300, visible: true });
  h.proj.set(B.id, { x: bx, y: 300, visible: true });
  h.proj.set(C.id, { x: 1500, y: 300, visible: true });
};

/* B's box starts 2 px past A's box plus the 4 px gutter: inside the 3 px hysteresis margin, so a
   label already SHOWN keeps its slot while moving and a HIDDEN one does not earn it back. With no
   margin it is clear. The ±1-row escape is blocked for a hidden label by the same margin. */
const FINAL_BX = 300 + W + 4 + 1;

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

/** Arrive at FINAL_BX from `startBx`, the scene reporting `moving` throughout the approach. */
const arrive = (startBx: number, sceneReportsSettle: boolean): string[] => {
  const h = mountLabels();
  h.sceneSettled.value = false;
  pose(h, startBx);
  flush(4);
  pose(h, FINAL_BX);
  flush(2);
  h.sceneSettled.value = sceneReportsSettle;
  flush(3);
  const out = h.visible();
  h.unmount();
  return out;
};

describe("DOM label declutter: the settled set is a pure function of the final pose (acceptance F6)", () => {
  it("while the scene is still moving, the history decides (so the settled pass is not vacuous)", () => {
    const fromApart = arrive(900, false);
    const fromOnTop = arrive(300, false);
    expect(fromApart).toContain(B.id);
    expect(fromOnTop).not.toContain(B.id);
  });

  it("two different paths onto the same final pose settle to the same visible set", () => {
    const fromApart = arrive(900, true);
    const fromOnTop = arrive(300, true);
    expect(fromApart).toEqual(fromOnTop);
    // And that set is the one a fresh load straight into the final pose settles to.
    const h = mountLabels();
    h.sceneSettled.value = true;
    pose(h, FINAL_BX);
    flush(4);
    expect(h.visible()).toEqual(fromApart);
    h.unmount();
    expect(fromApart).toEqual([A.id, B.id, C.id].sort());
  });

  it("a scene without labelsSettled settles on a held projection alone", () => {
    const h = mountLabels();
    pose(h, 300);
    flush(4);
    expect(h.visible()).not.toContain(B.id);
    pose(h, FINAL_BX);
    flush(3);
    expect(h.visible()).toContain(B.id);
    h.unmount();
  });

  it("no staggered drop survives into the settled frame", () => {
    // Three labels shown apart, then B and C land on A in one frame. Moving, one may leave per
    // LABEL_DROP_EVERY_FRAMES ticks; settled, every loser leaves on the same tick.
    const h = mountLabels();
    h.sceneSettled.value = false;
    h.proj.set(A.id, { x: 300, y: 300, visible: true });
    h.proj.set(B.id, { x: 800, y: 300, visible: true });
    h.proj.set(C.id, { x: 1300, y: 300, visible: true });
    flush(4);
    expect(h.visible()).toHaveLength(3);
    h.proj.set(B.id, { x: 300, y: 300, visible: true });
    h.proj.set(C.id, { x: 300, y: 300, visible: true });
    flush(1);
    const moving = h.visible().length;
    h.sceneSettled.value = true;
    flush(2);
    const settled = h.visible();
    h.unmount();

    const fresh = mountLabels();
    fresh.sceneSettled.value = true;
    fresh.proj.set(A.id, { x: 300, y: 300, visible: true });
    fresh.proj.set(B.id, { x: 300, y: 300, visible: true });
    fresh.proj.set(C.id, { x: 300, y: 300, visible: true });
    flush(4);
    expect(settled).toEqual(fresh.visible());
    fresh.unmount();
    expect(moving).toBeGreaterThan(settled.length);
  });
});
