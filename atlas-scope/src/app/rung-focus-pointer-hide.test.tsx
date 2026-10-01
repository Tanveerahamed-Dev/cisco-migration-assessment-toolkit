/**
 * rung-focus-pointer-hide.test.tsx — the fabric's off-view finding pointer is one more member of the
 * class D3-R2-1 names: a control HIDDEN on a resize (or a re-projection) while it holds focus
 * (independent verifier R5-V2).
 *
 * THE DEFECT. FabricLabels.tsx hides a pointer imperatively (`el.hidden = true`) when its device comes
 * into view — after the reader activated it to frame the device, or after the stage was resized — and
 * then called `onPointerFocusLost`, which Fabric3D.tsx answered with a bare
 * `canvasRef.current?.focus()`: a focus decision made outside focus-return.ts, which never checked
 * that the canvas took focus or could (a canvas under an `inert` stage, or in a stage the layout had
 * just stopped rendering, refuses it, and the browser then parks focus on <body>). Guard shapes 4 and 5
 * parse only JSX `hidden`/`inert` attributes and ladder-keyed renders, so an imperative hide passed
 * both.
 *
 * THE RULE UNDER TEST. The hide goes through the owner's THIRD DOOR (`releaseFocusFrom`), before the
 * pointer stops being rendered: the stage's stated successors (what `onPointerFocusLost` returns —
 * Fabric3D names its canvas) first, and when none of them can take focus the owner's own order (the
 * landmark around the pointer, then the nearest real tab stop outside it) — never the hidden pointer,
 * never <body>. jsdom performs no focus fix-up, so a pointer hidden around its focus KEEPS
 * `document.activeElement`: "focus is still on a hidden element" is exactly the drop a browser turns
 * into <body> at its next rendering step.
 */
import { act, useCallback, useRef, type ReactElement, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";
import type { FabricScene } from "../fabric3d/contract";
import { createHoverChannel, FabricLabels } from "../fabric3d/FabricLabels";

type P = { x: number; y: number; visible: boolean };

/* A finding that names exactly one device, resolved from the data rather than assumed. */
const FINDING = fabric.findings.find((f) => f.devices.length === 1)!;
const TARGET = fabric.devices.find((d) => FINDING.devices.includes(d.host) || FINDING.devices.includes(d.id))!;
const OTHER = fabric.devices.find((d) => d.id !== TARGET.id)!;
const DEVICES: Device[] = [TARGET, OTHER];
const STAGE = { w: 1200, h: 800 };
const PTR = { w: 170, h: 26 };

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
const rect = (x: number, y: number, w: number, h: number) =>
  (): DOMRect => ({ left: x, top: y, right: x + w, bottom: y + h, width: w, height: h, x, y, toJSON: () => ({}) }) as DOMRect;

interface Harness {
  proj: Map<string, P>;
  canvas(): HTMLCanvasElement;
  pointer(): HTMLElement;
  unmount(): void;
}

/**
 * The stage as Fabric3D lays it out: a named region holding the canvas and the label/pointer layers,
 * with the successor handed back by `onPointerFocusLost` (Fabric3D: its canvas). `canvasInert` puts the
 * canvas under an `inert` wrapper — a stated successor that refuses focus.
 */
function mount(canvasInert: boolean): Harness {
  const proj = new Map<string, P>();
  const scene = { project: (id: string) => proj.get(id) ?? null, focusDevice: () => {} } as unknown as FabricScene;
  const sceneRef: RefObject<FabricScene | null> = { current: scene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const finding = { id: FINDING.id, severity: String(FINDING.severity).toLowerCase(), hosts: new Set(FINDING.devices) };

  function Stage(): ReactElement {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const stageRef = useCallback((el: HTMLElement | null) => {
      const labels = el?.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]');
      if (labels) labels.getBoundingClientRect = rect(0, 0, STAGE.w, STAGE.h);
    }, []);
    return (
      <section aria-label="Fabric" ref={stageRef}>
        <div inert={canvasInert || undefined}>
          <canvas tabIndex={0} ref={canvasRef} className="stage-canvas" />
        </div>
        <FabricLabels
          devices={DEVICES}
          sceneRef={sceneRef}
          epoch={0}
          hover={createHoverChannel()}
          selectedId={null}
          finding={finding}
          onPointerFocusLost={() => [canvasRef.current]}
        />
      </section>
    );
  }

  act(() => {
    root.render(<Stage />);
  });
  container.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]')!.getBoundingClientRect = rect(0, 0, STAGE.w, STAGE.h);
  for (const el of container.querySelectorAll<HTMLElement>("[data-pointer-for]")) {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => PTR.w });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => PTR.h });
  }
  return {
    proj,
    canvas: () => container.querySelector<HTMLCanvasElement>("canvas.stage-canvas")!,
    pointer: () => container.querySelector<HTMLElement>(`[data-pointer-for="${TARGET.id}"]`)!,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

/** Focus the drawn pointer, then bring its device on stage (a resize, or the frame it asked for). */
function hideAroundFocus(h: Harness): HTMLElement {
  h.proj.set(TARGET.id, { x: 600, y: 1500, visible: false });
  h.proj.set(OTHER.id, { x: 300, y: 300, visible: true });
  flush(4);
  const ptr = h.pointer();
  expect(ptr.hidden, "precondition: the pointer is drawn (its device projects off the stage)").toBe(false);
  act(() => {
    ptr.focus();
  });
  expect(document.activeElement, "precondition: the pointer holds focus").toBe(ptr);
  h.proj.set(TARGET.id, { x: 600, y: 400, visible: true });
  flush(3);
  expect(ptr.hidden, "precondition: the pointer left the stage").toBe(true);
  return ptr;
}

const where = (): string => {
  const a = document.activeElement;
  if (a === null || a === document.body) return "BODY";
  return `${a.tagName}${(a as HTMLElement).hidden ? " (hidden)" : ""} "${(a.getAttribute("aria-label") ?? a.textContent ?? "").trim().slice(0, 40)}"`;
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
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("an off-view pointer hidden around its focus releases it through focus-return's third door", () => {
  it("hands focus to the successor the stage states (its canvas), not left on the hidden pointer", () => {
    const h = mount(false);
    const ptr = hideAroundFocus(h);
    expect(document.activeElement, `focus stayed on the hidden pointer (${where()})`).not.toBe(ptr);
    expect(document.activeElement, `focus did not reach the stage's stated successor (${where()})`).toBe(h.canvas());
    h.unmount();
  });

  it("when the stated successor refuses focus (an inert canvas), the owner's own order finds a real landing — never <body>", () => {
    const h = mount(true);
    const ptr = hideAroundFocus(h);
    const a = document.activeElement;
    expect(a, `focus stayed on the hidden pointer (${where()})`).not.toBe(ptr);
    expect(a !== null && a !== document.body, `focus was dropped (${where()})`).toBe(true);
    expect(a!.closest("[hidden], [inert]"), `focus landed somewhere unrendered or inert (${where()})`).toBeNull();
    expect(a!.isConnected).toBe(true);
    h.unmount();
  });
});
