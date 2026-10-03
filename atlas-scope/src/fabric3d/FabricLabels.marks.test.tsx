/**
 * FabricLabels.marks.test.tsx — a MARK the fabric claims to show is one a reader can see.
 *
 * MEASURED (acceptance A6 refuter, 390x844, release build, `?d=core1` and a real canvas click):
 *   - core1's "⚠ CUT POINT" mark was fully under the stage HUD: 10 of 10 hit-test samples landed on
 *     `.fabric3d__quality` or `.fabric3d__hud`. core1 projects to the top of a 389 px stage, its label
 *     flipped below its anchor, every row it could move to read as a neighbour's name, and the forced
 *     label "kept its own anchor" — under the HUD.
 *   - access10's and access12's "⊘ STRANDED?" marks were fully under access8's and access4's labels
 *     (0 of 10 unoccluded): nine stranded hosts in a column of anchors ~20 px apart, every displaced
 *     row nearer a neighbour's anchor, so the forced labels piled onto their anchors.
 *   - and the HUD still said "core1 strands 9 … · all 9 marked", because the layer reported only the
 *     marks whose label was hidden, never the ones it had drawn under something else.
 *
 * The rule under test is the rule, not that one layout: every marked label the layer reports as drawn
 * is clear of every other drawn label and of every stage control, and a marked label it cannot place
 * so is REPORTED, never counted as marked. The stage here is the refuter's measured shape (a 390 x 389
 * canvas, the HUD's four controls at their measured boxes); the anchors are a stand-in column.
 */
import { act, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { createHoverChannel, FabricLabels } from "./FabricLabels";

type P = { x: number; y: number; visible: boolean };
interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const STAGE = { w: 390, h: 389 };
/* The HUD's controls as measured at 390x844 (canvas-relative): "Quality low", "Reset view", the
   blast note on a row of its own, "Fabric list". The container itself paints nothing. */
const HUD: Box[] = [
  { x: 225, y: 8, w: 83, h: 24 },
  { x: 312, y: 8, w: 70, h: 24 },
  { x: 10, y: 36, w: 372, h: 22 },
  { x: 318, y: 62, w: 64, h: 24 },
];
const LABEL_W = 150;
const LABEL_H = 16;
const NAME_LEFT = 4;
const NAME_W = 72;

const DEVICES: Device[] = fabric.devices.slice(0, 12);

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

const rect = (b: Box): DOMRect =>
  ({ left: b.x, top: b.y, right: b.x + b.w, bottom: b.y + b.h, width: b.w, height: b.h, x: b.x, y: b.y, toJSON: () => ({}) }) as DOMRect;
const boxAttr = (b: Box): string => `${b.x},${b.y},${b.w},${b.h}`;
const parseBox = (s: string): Box => {
  const [x, y, w, h] = s.split(",").map(Number) as [number, number, number, number];
  return { x, y, w, h };
};
const overlap = (a: Box, b: Box): boolean => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

const originalRect = HTMLElement.prototype.getBoundingClientRect;

interface Harness {
  label(id: string): HTMLElement;
  /** The box a label is drawn in, read back from the transform the layer wrote. */
  drawn(id: string): Box;
  unseen: { outOfView: readonly string[]; covered: readonly string[] };
  unmount(): void;
}

function mountStage(proj: ReadonlyMap<string, P>, opts: { selected: string | null; cut: string | null; stranded: readonly string[] }): Harness {
  /* Layout is supplied BEFORE the mount: the layer measures the stage and the HUD when it attaches. */
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.dataset["box"] !== undefined) return rect(parseBox(this.dataset["box"]));
    if (this.classList.contains("stage") || this.classList.contains("fabric3d__labels")) return rect({ x: 0, y: 0, ...STAGE });
    if (this.classList.contains("hud")) {
      const x0 = Math.min(...HUD.map((b) => b.x));
      const y0 = Math.min(...HUD.map((b) => b.y));
      return rect({ x: x0, y: y0, w: Math.max(...HUD.map((b) => b.x + b.w)) - x0, h: Math.max(...HUD.map((b) => b.y + b.h)) - y0 });
    }
    return originalRect.call(this) as DOMRect;
  };
  const scene = { project: (id: string) => proj.get(id) ?? null } as unknown as FabricScene;
  Object.defineProperty(scene, "labelsSettled", { get: () => () => true });
  const ref: RefObject<FabricScene | null> = { current: scene };
  const unseen: { outOfView: readonly string[]; covered: readonly string[] } = { outOfView: [], covered: [] };
  const report = (outOfView: readonly string[], covered?: readonly string[]): void => {
    unseen.outOfView = outOfView;
    unseen.covered = covered ?? [];
  };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  act(() => {
    root.render(
      <div className="stage">
        <FabricLabels
          devices={DEVICES}
          sceneRef={ref}
          epoch={0}
          hover={createHoverChannel()}
          selectedId={opts.selected}
          cutPointId={opts.cut}
          strandedIds={new Set(opts.stranded)}
          strandedQualifier="uncertain"
          onStrandedUnseen={report}
        />
        <div className="hud" data-label-keepout="">
          {HUD.map((b) => (
            <span key={boxAttr(b)} data-box={boxAttr(b)} />
          ))}
        </div>
      </div>,
    );
  });
  for (const el of container.querySelectorAll<HTMLElement>(".fabric3d-label")) {
    Object.defineProperty(el, "offsetWidth", { configurable: true, get: () => LABEL_W });
    Object.defineProperty(el, "offsetHeight", { configurable: true, get: () => LABEL_H });
    const name = el.firstElementChild as HTMLElement;
    Object.defineProperty(name, "offsetLeft", { configurable: true, get: () => NAME_LEFT });
    Object.defineProperty(name, "offsetWidth", { configurable: true, get: () => NAME_W });
  }
  const label = (id: string): HTMLElement => container.querySelector<HTMLElement>(`[data-device="${id}"]`)!;
  return {
    label,
    drawn: (id) => {
      const t = label(id).style.transform;
      const m = /translate3d\(([-\d.]+)px, ([-\d.]+)px, 0\) translate\(0, ([-\d.]+)%\)/.exec(t);
      if (!m) throw new Error(`unparsed transform for ${id}: "${t}"`);
      return { x: Number(m[1]), y: Number(m[2]) + (Number(m[3]) / 100) * LABEL_H, w: LABEL_W, h: LABEL_H };
    },
    unseen,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/** The invariant: every marked label the layer counts as drawn is legible. */
function legibility(h: Harness, marked: readonly string[]): { legible: string[]; problems: string[] } {
  const reported = new Set([...h.unseen.outOfView, ...h.unseen.covered]);
  const legible = marked.filter((id) => h.label(id).dataset["visible"] === "true" && !reported.has(id));
  const problems: string[] = [];
  for (const id of legible) {
    const b = h.drawn(id);
    if (b.x < 0 || b.y < 0 || b.x + b.w > STAGE.w || b.y + b.h > STAGE.h) problems.push(`${id} crosses the stage edge ${JSON.stringify(b)}`);
    for (const c of HUD) if (overlap(b, c)) problems.push(`${id} ${JSON.stringify(b)} is under the HUD control ${JSON.stringify(c)}`);
  }
  /* A legible mark must not be under ANY drawn label — marked or not. */
  const drawnIds = DEVICES.map((d) => d.id).filter((id) => h.label(id).dataset["visible"] === "true" && h.label(id).dataset["covered"] !== "yes");
  for (const id of legible) {
    for (const other of drawnIds) {
      if (other !== id && overlap(h.drawn(id), h.drawn(other))) problems.push(`${id} ${JSON.stringify(h.drawn(id))} overlaps ${other} ${JSON.stringify(h.drawn(other))}`);
    }
  }
  return { legible, problems };
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
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  vi.unstubAllGlobals();
});

const ids = DEVICES.map((d) => d.id);

describe("a marked label the fabric counts as shown is one a reader can see (A6)", () => {
  it("the selected cut point at the top of a phone-width stage is placed clear of the HUD's controls", () => {
    const [cut, n1, n2, n3] = ids as [string, string, string, string];
    /* The measured shape: the cut point projects under the blast note, and every row its label can
       move to lies nearer a neighbour's anchor (a column of devices straight below it). */
    const proj = new Map<string, P>([
      [cut, { x: 190, y: 20, visible: true }],
      [n1, { x: 190, y: 70, visible: true }],
      [n2, { x: 190, y: 110, visible: true }],
      [n3, { x: 190, y: 150, visible: true }],
    ]);
    const h = mountStage(proj, { selected: cut, cut, stranded: [] });
    flush(6);
    expect(h.label(cut).dataset["cut"]).toBe("yes");
    expect(h.label(cut).dataset["visible"], "the selected cut point is always labelled").toBe("true");
    const b = h.drawn(cut);
    for (const c of HUD) expect(overlap(b, c), `the CUT POINT mark ${JSON.stringify(b)} under the HUD control ${JSON.stringify(c)}`).toBe(false);
    expect(h.unseen.covered).toEqual([]);
    h.unmount();
  });

  it("a column of nine stranded hosts: every mark is drawn clear of every label and of the HUD", () => {
    const [cut, ...rest] = ids as [string, ...string[]];
    const stranded = rest.slice(0, 9);
    const proj = new Map<string, P>([[cut, { x: 200, y: 24, visible: true }]]);
    /* Anchors 20 px apart down a staggered column: a label is 16 px tall with a 6 px row gutter, so
       no two can keep their home slots, and every displaced row is nearer a neighbour's anchor. */
    stranded.forEach((id, i) => proj.set(id, { x: 150 + (i % 2) * 40, y: 110 + i * 20, visible: true }));
    for (const id of rest.slice(9)) proj.set(id, { x: 330, y: 360, visible: true });
    const h = mountStage(proj, { selected: cut, cut, stranded });
    flush(6);
    const { legible, problems } = legibility(h, [cut, ...stranded]);
    expect(problems, problems.join("\n")).toEqual([]);
    // There is room on this stage for all of them, so none may be given up.
    expect(legible.sort()).toEqual([cut, ...stranded].sort());
    h.unmount();
  });

  it("a stage too small to hold them all REPORTS each mark it could not draw legibly — never counts it as marked", () => {
    const [cut, ...rest] = ids as [string, ...string[]];
    const stranded = rest.slice(0, 11);
    const proj = new Map<string, P>([[cut, { x: 200, y: 24, visible: true }]]);
    // Eleven labels piled on two points in the band below the HUD: more than the stage can hold.
    stranded.forEach((id, i) => proj.set(id, { x: 120 + (i % 2) * 150, y: 200, visible: true }));
    const h = mountStage(proj, { selected: cut, cut, stranded });
    flush(6);
    const { legible, problems } = legibility(h, [cut, ...stranded]);
    expect(problems, problems.join("\n")).toEqual([]);
    const accounted = new Set([...legible, ...h.unseen.outOfView, ...h.unseen.covered]);
    for (const id of [cut, ...stranded]) expect(accounted.has(id), `${id} is neither legibly drawn nor reported`).toBe(true);
    h.unmount();
  });
});
