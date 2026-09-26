/**
 * FabricLabels.pointer.test.tsx — the off-view finding pointer is a real control (acceptance D1, D5).
 *
 * MEASURED (acceptance report at 78bdba5, refuter `ptr3.mjs`, 1440x900, `?f=F094`): the pointer for
 * access5 was a `<span onClick>` inside the label layer's `aria-hidden="true"` container, with no role,
 * `tabIndex -1` and no key handler. A click at its centre framed access5; a 250-stop Tab walk never
 * reached it ("pointer reached: false"); it measured 141.23 x 16.84 CSS px; and in the dark theme it
 * sat under the blast-radius HUD, where a click did nothing.
 *
 * What these tests pin, in jsdom (which lays nothing out and performs no keyboard activation):
 *   - it is a native `<button type="button">` — Enter and Space activate a button by the platform's
 *     own contract, which jsdom does not implement; the real keys are driven in a browser
 *     (review/audit-d3-focus.mjs, and the ptr3 re-run recorded with this wave);
 *   - it is in the sequential focus order and has no aria-hidden (or inert) ancestor, so a keyboard
 *     and a screen-reader user meet the control a mouse user sees;
 *   - activating it frames the host (`focusDevice`), and nothing on the way cancels a key's default;
 *   - it is placed clear of every `[data-label-keepout]` box (the HUD), inside the stage;
 *   - when it leaves (the host is framed), it stops being focusable, and focus it held is handed on
 *     rather than dropped to <body>.
 * Its 24 px floor is a CSS fact: src/ui/target-size.test.ts judges it from source, and the browser
 * census in review/audit-d3-focus.mjs measures it with getBoundingClientRect.
 */
import { act, useCallback, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels } from "./FabricLabels";

type P = { x: number; y: number; visible: boolean };

/* F094 names only access5 — the refuter's case. Resolved from the data, not assumed. */
const FINDING = fabric.findings.find((f) => f.id === "F094") ?? fabric.findings.find((f) => f.devices.length === 1)!;
const TARGET = fabric.devices.find((d) => FINDING.devices.includes(d.host) || FINDING.devices.includes(d.id))!;
const OTHER = fabric.devices.find((d) => d.id !== TARGET.id)!;
const DEVICES: Device[] = [TARGET, OTHER];

const STAGE = { w: 1200, h: 800 };
/** The HUD's box in the top-right corner of the stage, as Fabric3D.tsx draws it. */
const HUD = { x: 700, y: 8, w: 492, h: 34 };
const PTR = { w: 170, h: 26 };

let frames = new Map<number, FrameRequestCallback>();
let nextId = 1;
const flush = (n = 1): void => {
  for (let i = 0; i < n; i += 1) {
    const batch = [...frames.values()];
    frames = new Map();
    for (const cb of batch) cb(0);
  }
};

const rect = (x: number, y: number, w: number, h: number) =>
  (): DOMRect => ({ left: x, top: y, right: x + w, bottom: y + h, width: w, height: h, x, y, toJSON: () => ({}) }) as DOMRect;

interface Harness {
  container: HTMLElement;
  proj: Map<string, P>;
  focusDevice: ReturnType<typeof vi.fn>;
  focusLost: ReturnType<typeof vi.fn>;
  pointer(): HTMLElement | null;
  unmount(): void;
}

function mount(withHud: boolean): Harness {
  const proj = new Map<string, P>();
  const focusDevice = vi.fn();
  const focusLost = vi.fn();
  const scene = { project: (id: string) => proj.get(id) ?? null, focusDevice } as unknown as FabricScene;
  const ref: RefObject<FabricScene | null> = { current: scene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const finding = { id: FINDING.id, severity: FINDING.severity.toLowerCase(), hosts: new Set(FINDING.devices) };

  function Stage() {
    /* Ref callbacks run before the label layer's effect attaches, so the stage and the keep-out are
       measured with these boxes, exactly as the observer would report them. */
    const stageRef = useCallback((el: HTMLDivElement | null) => {
      const labels = el?.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]');
      if (labels) labels.getBoundingClientRect = rect(0, 0, STAGE.w, STAGE.h);
    }, []);
    const hudRef = useCallback((el: HTMLDivElement | null) => {
      if (el) el.getBoundingClientRect = rect(HUD.x, HUD.y, HUD.w, HUD.h);
    }, []);
    return (
      <div ref={stageRef}>
        <canvas tabIndex={0} />
        <FabricLabels
          devices={DEVICES}
          sceneRef={ref}
          epoch={0}
          hover={createHoverChannel()}
          selectedId={null}
          finding={finding}
          onPointerFocusLost={focusLost}
        />
        {withHud ? <div data-label-keepout="" ref={hudRef} /> : null}
      </div>
    );
  }

  act(() => root.render(<Stage />));
  const labels = container.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]')!;
  labels.getBoundingClientRect = rect(0, 0, STAGE.w, STAGE.h);
  const sizeUp = (el: HTMLElement): void => {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => PTR.w });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => PTR.h });
  };
  for (const el of container.querySelectorAll<HTMLElement>("[data-pointer-for]")) sizeUp(el);
  return {
    container,
    proj,
    focusDevice,
    focusLost,
    pointer: () => container.querySelector<HTMLElement>(`[data-pointer-for="${TARGET.id}"]`),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/** The pointer's box in stage space, from the transform the layer wrote (centred on px, py). */
function boxOf(el: HTMLElement): { x: number; y: number; w: number; h: number } {
  const m = /translate3d\((-?[\d.]+)px, (-?[\d.]+)px/.exec(el.style.transform);
  if (m === null) throw new Error(`no position written: "${el.style.transform}"`);
  return { x: Number(m[1]) - PTR.w / 2, y: Number(m[2]) - PTR.h / 2, w: PTR.w, h: PTR.h };
}

/** The sequential focus navigation order jsdom can compute: focusable, not hidden, not disabled. */
function tabOrder(): Element[] {
  return [...document.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]")].filter(
    (el) =>
      el.tabIndex >= 0 &&
      !(el as HTMLButtonElement).disabled &&
      !el.hidden &&
      el.closest("[hidden], [inert]") === null,
  );
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
  vi.unstubAllGlobals();
});

describe("the off-view finding pointer is a real, keyboard-reachable control (acceptance D1, D5)", () => {
  it("is a named <button> outside every aria-hidden subtree, in the Tab order after the canvas", () => {
    const h = mount(false);
    h.proj.set(TARGET.id, { x: 600, y: 1500, visible: false }); // below the stage
    h.proj.set(OTHER.id, { x: 300, y: 300, visible: true });
    flush(4);
    const ptr = h.pointer();
    expect(ptr, "an off-canvas finding host gets a pointer").not.toBeNull();
    expect(ptr!.dataset["visible"]).toBe("true");
    expect(ptr!.tagName, "a native button: Enter and Space activate it by the platform's contract").toBe("BUTTON");
    expect(ptr!.getAttribute("type")).toBe("button");
    expect(ptr!.closest('[aria-hidden="true"]'), "an operable control hidden from assistive technology").toBeNull();
    expect(ptr!.closest("[inert]")).toBeNull();
    expect(ptr!.hidden).toBe(false);
    const order = tabOrder();
    expect(order, "the pointer is in the sequential focus order").toContain(ptr);
    const canvas = h.container.querySelector("canvas")!;
    expect(order.indexOf(ptr!), "reached after the canvas it points out of").toBeGreaterThan(order.indexOf(canvas));
    /* Its name is what it says on screen — the finding and the host — and it does not re-read every
       hostname: the label layer beside it stays hidden from assistive technology. */
    const spoken = [...ptr!.childNodes]
      .filter((n) => !(n instanceof HTMLElement && n.getAttribute("aria-hidden") === "true"))
      .map((n) => n.textContent ?? "")
      .join("")
      .replace(/\s+/g, " ")
      .trim();
    expect(spoken).toContain(FINDING.id);
    expect(spoken).toContain(TARGET.host);
    expect(h.container.querySelector('[data-testid="fabric3d-labels"]')?.getAttribute("aria-hidden")).toBe("true");
    ptr!.focus();
    expect(document.activeElement).toBe(ptr);
    h.unmount();
  });

  it("activating it frames the host, and no handler cancels Enter or Space", () => {
    const h = mount(false);
    h.proj.set(TARGET.id, { x: -400, y: 300, visible: false }); // left of the stage
    h.proj.set(OTHER.id, { x: 300, y: 300, visible: true });
    flush(4);
    const ptr = h.pointer()!;
    expect(ptr.tagName).toBe("BUTTON");
    for (const key of ["Enter", " "]) {
      const ev = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
      act(() => {
        ptr.dispatchEvent(ev);
      });
      expect(ev.defaultPrevented, `keydown "${key}" was cancelled before the button could activate`).toBe(false);
    }
    /* The activation Enter and Space produce on a native button is a click; jsdom does not synthesise
       it from the key, so it is dispatched here as the platform would. */
    act(() => ptr.click());
    expect(h.focusDevice).toHaveBeenCalledTimes(1);
    expect(h.focusDevice).toHaveBeenLastCalledWith(TARGET.id);
    h.unmount();
  });

  it("is placed clear of the HUD's keep-out box and inside the stage", () => {
    const h = mount(true);
    /* Up and to the right: the unobstructed edge point falls on the HUD in the top-right corner. */
    h.proj.set(TARGET.id, { x: 1150, y: -300, visible: false });
    h.proj.set(OTHER.id, { x: 300, y: 300, visible: true });
    flush(4);
    const ptr = h.pointer()!;
    expect(ptr.dataset["visible"]).toBe("true");
    const b = boxOf(ptr);
    const overlaps = b.x < HUD.x + HUD.w && b.x + b.w > HUD.x && b.y < HUD.y + HUD.h && b.y + b.h > HUD.y;
    expect(overlaps, `pointer box ${JSON.stringify(b)} lies under the HUD ${JSON.stringify(HUD)}`).toBe(false);
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.y).toBeGreaterThanOrEqual(0);
    expect(b.x + b.w).toBeLessThanOrEqual(STAGE.w);
    expect(b.y + b.h).toBeLessThanOrEqual(STAGE.h);
    h.unmount();
  });

  it("stops being focusable when it leaves, and hands on the focus it held instead of dropping it", () => {
    const h = mount(false);
    h.proj.set(TARGET.id, { x: 600, y: 1500, visible: false });
    h.proj.set(OTHER.id, { x: 300, y: 300, visible: true });
    flush(4);
    const ptr = h.pointer()!;
    ptr.focus();
    expect(document.activeElement).toBe(ptr);
    act(() => ptr.click());
    // The camera framed the host: it now projects on the stage, and the pointer goes.
    h.proj.set(TARGET.id, { x: 600, y: 400, visible: true });
    flush(3);
    expect(ptr.dataset["visible"]).toBe("false");
    expect(ptr.hidden, "a hidden pointer must not stay in the Tab order").toBe(true);
    expect(tabOrder()).not.toContain(ptr);
    expect(h.focusLost, "focus on the leaving pointer is handed to the stage, not dropped").toHaveBeenCalledTimes(1);
    h.unmount();
  });
});
