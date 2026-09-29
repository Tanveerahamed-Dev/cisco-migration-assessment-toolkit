/**
 * FabricLabels.dwell.test.tsx — the DOM label layer cannot blink, and it cannot disagree with the
 * scene's resolver about WHEN a name may appear or leave (acceptance C5, label popping).
 *
 * THE DEFECT (motion audit, 2026-09-22, real GPU, the harness's six camera sequences). The scene's
 * resolver (`labelResolve.ts :: resolveLabels`) recorded NO blink on any sequence, while the DOM
 * labels the reader actually sees blinked on four of six: `access13 shown 2f` and `access16 hidden
 * 4f` in an orbit drag, `core1 hidden 4f` in a dolly, `access2`/`access4` 2–4 frame runs at a focus
 * fly, `access10 hidden 3f`/`access15 hidden 1f` at a reset fly. The DOM declutter had its own
 * spatial hysteresis and stagger, but NO time dwell, and it let a hidden name reappear while the
 * camera moved — the two guards `labelResolve.ts` already carried. Two surfaces each owning a
 * show/hide rule is the defect shape; the fix routes both through ONE gate (`labelDwellVerdict`).
 *
 * The rules are restated here from the design (not read from the gate), and exercised on the REAL
 * FabricLabels component with a scripted scene whose projections move exactly as a camera would:
 *   1. while the camera moves, a hidden name does not appear; it appears once the camera is still;
 *   2. a name that has just appeared does not leave within LABEL_MIN_DWELL_PASSES passes;
 *   3. an overlap that comes and goes while the camera moves produces no visibility run of 5
 *      frames or fewer (the probe's own blink definition);
 *   4. the same want-sequence through the DOM layer and through `resolveLabels` gives the same
 *      visibility timeline, frame for frame.
 * Marked (forced) labels and the settled pass are exempt and pinned as exempt, so the gate is not
 * tested only where it is inert.
 */
import { act, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import type { Device } from "../core/types";

import type { FabricScene } from "./contract";
import { LABEL_DROP_EVERY_FRAMES } from "./emphasis";
import { createHoverChannel, FabricLabels } from "./FabricLabels";
import { LABEL_MIN_DWELL_PASSES, resolveLabels, type LabelResolverState } from "./labelResolve";

type P = { x: number; y: number; visible: boolean };

/* Three devices, in the order FabricLabels places them (busiest — most links — first, then by host): A outranks B,
   so when B lands on A it is B that must yield. They are chosen BY THAT PROPERTY from the loaded fabric (P3C-V2-3):
   the first three device RECORDS used to stand in, which held only while the sample's record order happened to be
   the placement order — on the rename leg B outranked A and every test here inverted. The three least-linked
   devices are taken, so none is a cut point whose marks could force another label on screen. */
const linkCount = (d: Device): number => fabric.links.filter((l) => l.a === d.host || l.b === d.host || l.a === d.id || l.b === d.id).length;
const PLACED = [...fabric.devices].sort((a, b) => linkCount(b) - linkCount(a) || a.host.localeCompare(b.host));
const [A, B, C] = PLACED.slice(-3) as [Device, Device, Device];
const DEVICES: Device[] = [A, B, C];

/* Every label is 100 x 16 with its name centred, so a label's box is [x - 50, x + 50]. */
const W = 100;
const H = 16;
/* Anchors sit near the TOP of the stage, so B's one-row-up escape slot falls off the stage and its
   one-row-down slot lands on A's chassis zone: B on A is genuinely blocked, not displaced. */
const ROW_Y = 40;
const A_X = 300;
const APART_X = 1000;
const C_X = 1700;

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
  visible(id: string): boolean;
  rerender(selectedId: string | null): void;
  hover(deviceId: string | null): void;
  unmount(): void;
}

function mountLabels(sceneOverride?: (proj: Map<string, P>) => FabricScene): Harness {
  const proj = new Map<string, P>();
  /* A scene that is never idle: every still tick is "still", never "settled", so the moving-camera
     rules are what is exercised (the settled pass is pinned separately below). */
  const scene =
    sceneOverride?.(proj) ??
    ({
      project: (id: string) => proj.get(id) ?? null,
      labelsSettled: () => false,
    } as unknown as FabricScene);
  const ref: RefObject<FabricScene | null> = { current: scene };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const hover = createHoverChannel();
  const render = (selectedId: string | null): void =>
    act(() => {
      root.render(<FabricLabels devices={DEVICES} sceneRef={ref} epoch={0} hover={hover} selectedId={selectedId} />);
    });
  render(null);
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
    visible: (id) => container.querySelector<HTMLElement>(`.fabric3d-label[data-device="${id}"]`)?.dataset.visible === "true",
    rerender: render,
    hover: (deviceId) => act(() => { hover.set({ deviceId, linkId: null }); }),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/**
 * One frame of the scripted camera. `onA` puts B on A's anchor (blocked); otherwise B is far apart
 * (clear). `pan` shifts every anchor by that many px — a camera move changes every projection, a
 * still camera none.
 */
const place = (h: Harness, onA: boolean, pan: number): void => {
  h.proj.set(A.id, { x: A_X, y: ROW_Y + pan, visible: true });
  h.proj.set(B.id, { x: onA ? A_X : APART_X, y: ROW_Y + pan, visible: true });
  h.proj.set(C.id, { x: C_X, y: ROW_Y + pan, visible: true });
};

interface Step {
  /** B's box is free this frame. */
  clear: boolean;
  /** The camera moved this frame. */
  moving: boolean;
}

/** Drive the DOM layer one frame per step; returns B's visibility per frame. */
function domTimeline(steps: readonly Step[]): boolean[] {
  const h = mountLabels();
  const out: boolean[] = [];
  let pan = 0;
  for (const s of steps) {
    if (s.moving) pan = pan === 0 ? 1 : 0;
    place(h, !s.clear, pan);
    flush(1);
    out.push(h.visible(B.id));
  }
  h.unmount();
  return out;
}

/** Drive `resolveLabels` with the same want-sequence (A nearer, so A takes the box). */
function resolverTimeline(steps: readonly Step[]): boolean[] {
  const state: LabelResolverState = {
    wasKept: new Uint8Array(2),
    pending: new Uint8Array(2),
    passesSinceDrop: LABEL_DROP_EVERY_FRAMES,
    age: new Uint16Array(2).fill(0xffff),
  };
  const out: boolean[] = [];
  for (const s of steps) {
    const boxes = new Float32Array([0, 0, 100, 16, ...(s.clear ? [700, 0, 800, 16] : [0, 0, 100, 16])]);
    const r = resolveLabels(
      {
        boxes,
        classOf: [60, 60],
        distance: [10, 20],
        hysteresisPx: 3,
        dropEveryPasses: LABEL_DROP_EVERY_FRAMES,
        settled: false,
        cameraMoving: s.moving,
      },
      state,
    );
    out.push(r.kept[1] === 1);
  }
  return out;
}

/** Runs of an unchanged value of length <= 5 that start after frame 0 and end before the last frame:
 *  exactly the motion probe's blink definition. */
function blinks(t: readonly boolean[]): string[] {
  const out: string[] = [];
  let start = 0;
  for (let i = 1; i <= t.length; i += 1) {
    if (i < t.length && t[i] === t[i - 1]) continue;
    const len = i - start;
    if (start > 0 && i < t.length && len <= 5) out.push(`${t[start] ? "shown" : "hidden"} ${len}f @${start}`);
    start = i;
  }
  return out;
}

const still = (n: number, clear: boolean): Step[] => Array.from({ length: n }, () => ({ clear, moving: false }));
const moving = (n: number, clear: boolean | ((i: number) => boolean)): Step[] =>
  Array.from({ length: n }, (_, i) => ({ clear: typeof clear === "function" ? clear(i) : clear, moving: true }));

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

describe("DOM labels: one dwell gate, shared with the scene resolver (acceptance C5, label popping)", () => {
  it("precondition: B on A is blocked and B apart is clear on a still camera", () => {
    const t = domTimeline([...still(6, true), ...moving(1, false), ...still(40, false)]);
    expect(t[5], "B apart is shown on a still camera").toBe(true);
    expect(t[t.length - 1], "B on A is decluttered on a still camera").toBe(false);
  });

  it("while the camera moves, a hidden name does not appear; it appears once the camera is still", () => {
    // Hidden under A long enough to be past any dwell, then the camera moves and B's box clears.
    const steps = [...moving(1, false), ...still(30, false), ...moving(20, true), ...still(4, true)];
    const t = domTimeline(steps);
    expect(t.slice(0, 31).some(Boolean), "B is hidden while on A").toBe(false);
    expect(t.slice(31, 51).filter(Boolean).length, "B appeared while the camera was moving").toBe(0);
    expect(t.slice(51).some(Boolean), "B never appeared once the camera was still").toBe(true);
  });

  it("a name that has just appeared does not leave within the dwell, even when its box is taken", () => {
    const steps = [...moving(1, true), ...still(3, true), ...moving(LABEL_MIN_DWELL_PASSES + 12, false)];
    const t = domTimeline(steps);
    const appeared = t.indexOf(true);
    expect(appeared, "B never appeared").toBeGreaterThanOrEqual(0);
    for (let i = appeared; i < appeared + LABEL_MIN_DWELL_PASSES && i < t.length; i += 1) {
      expect(t[i], `B left at frame ${i}, ${i - appeared} passes after appearing`).toBe(true);
    }
    expect(t[t.length - 1], "B must still leave once the dwell has run out").toBe(false);
  });

  it("an overlap that comes and goes while the camera moves draws no blink", () => {
    // Settled on screen well past any dwell, then 60 moving frames in which B's box is taken for 3
    // frames and free for 3 — a slow slide of two boxes past each other, as in an orbit.
    const steps = [...moving(1, true), ...still(40, true), ...moving(60, (i) => Math.floor(i / 3) % 2 === 1), ...still(30, true)];
    const t = domTimeline(steps);
    expect(blinks(t)).toEqual([]);
  });

  it("the DOM layer and the scene resolver give the same timeline for the same want-sequence", () => {
    const sequences: Step[][] = [
      [...moving(1, false), ...still(30, false), ...moving(20, true), ...still(20, true)],
      [...moving(1, true), ...still(3, true), ...moving(30, false), ...still(10, false)],
      [...moving(1, true), ...still(40, true), ...moving(60, (i) => Math.floor(i / 3) % 2 === 1), ...still(30, true)],
      [...moving(1, true), ...still(2, true), ...moving(40, (i) => i % 7 < 2), ...still(20, false)],
    ];
    for (const [k, steps] of sequences.entries()) {
      const dom = domTimeline(steps);
      const scene = resolverTimeline(steps);
      expect(dom, `sequence ${k}: the DOM layer and resolveLabels disagree`).toEqual(scene);
    }
  });

  it("a marked label is exempt: the selected host's name shows at once while the camera moves", () => {
    const h = mountLabels();
    place(h, true, 0);
    flush(4);
    expect(h.visible(B.id)).toBe(false);
    h.rerender(B.id);
    place(h, true, 1);
    flush(1);
    expect(h.visible(B.id), "a forced label waited on the dwell").toBe(true);
    h.unmount();
  });

  it("a hovered name is pointed at only on a still camera: an orbit drag sweeping over a device does not pop its name", () => {
    /* MEASURED (motion probe, high tier, orbit drag, 3 of 3 runs, after the dwell gate): access16
       left under the dwell's rules and, 2-4 frames later, came straight back because the DRAG's
       pointer crossed its chassis and hover exempted it — during a drag the pointer sweeps across
       devices without pointing at any of them. So hover is urgent only while the camera is still. */
    const h = mountLabels();
    place(h, true, 0);
    flush(40);
    expect(h.visible(B.id), "precondition: B on A is decluttered").toBe(false);
    h.hover(B.id);
    const whileMoving: boolean[] = [];
    for (let i = 1; i <= 10; i += 1) {
      place(h, true, i % 2);
      flush(1);
      whileMoving.push(h.visible(B.id));
    }
    expect(whileMoving.some(Boolean), "the hovered name popped in while the camera moved").toBe(false);
    flush(1); // the camera stops, pointer still on B
    expect(h.visible(B.id), "a hovered name on a still camera shows at once").toBe(true);
    h.unmount();
  });
});

describe("DOM labels: the settled pass does not reverse a name younger than the dwell (C5 residual)", () => {
  /* MEASURED (review/capture-motion.mjs, light/high/dolly-in, 2026-09-22): "access12 hidden for only
     5 frame(s)" in a move of six moving frames. The name left at the start of the move; the move
     ended before its dwell did; and the history-free settled pass (F6) — which this layer runs as
     soon as the scene says it is settled and the pose holds — put it straight back. The DOM layer
     cannot hold the scene's settle itself, so it REPORTS whether it is still converging
     (`reportLabelsConverging`, labelResolve `labelSettleMayReverse`), and a scene that honours the
     report withholds `labelsSettled()` (and its `converged`) meanwhile. The scene below honours it
     exactly that way; without the report it settles at once, which is today's scene.ts.

     Geometry: A at (300, 40). B shown far apart for a long spell, covered by A for two moving
     frames (it leaves), then at rest at (405, 40): its box 5 px from A's — clear of the side gutter with no margin, not
     clear by the hidden margin. C at (405, 58) makes B's one-row-down escape read as C's name,
     so B cannot simply be displaced. */
  const cooperative = (log: boolean[]) => (proj: Map<string, P>): FabricScene => {
    let converging = false;
    return {
      project: (id: string) => proj.get(id) ?? null,
      labelsSettled: () => !converging,
      reportLabelsConverging: (b: boolean) => {
        converging = b;
        log.push(b);
      },
    } as unknown as FabricScene;
  };
  /* 5 px apart: clear of the 4 px side gutter with no margin, not by the 3 px hidden margin. */
  const REST_B_X = A_X + W + 5;
  const at = (h: Harness, phase: "apart" | "covered" | "rest", pan: number): void => {
    h.proj.set(A.id, { x: A_X, y: ROW_Y + pan, visible: true });
    h.proj.set(B.id, { x: phase === "apart" ? APART_X : phase === "covered" ? A_X : REST_B_X, y: ROW_Y + pan, visible: true });
    h.proj.set(C.id, phase === "rest" ? { x: REST_B_X, y: ROW_Y + 18 + pan, visible: true } : { x: C_X, y: ROW_Y + pan, visible: true });
  };
  const timeline = (h: Harness): boolean[] => {
    const out: boolean[] = [];
    const step = (phase: "apart" | "covered" | "rest", pan: number): void => {
      at(h, phase, pan);
      flush(1);
      out.push(h.visible(B.id));
    };
    for (let i = 0; i < 40; i += 1) step("apart", 0);
    step("covered", 1);
    step("covered", 0);
    step("rest", 1); // arrives
    for (let i = 0; i < 40; i += 1) step("rest", 1);
    return out;
  };

  it("preconditions: at rest the history-free answer shows B, and the moving-camera margin does not", () => {
    // A scene that is settled whenever the pose holds (no report honoured): B is shown at rest.
    const settles = mountLabels((proj) => ({ project: (id: string) => proj.get(id) ?? null, labelsSettled: () => true }) as unknown as FabricScene);
    at(settles, "rest", 0);
    flush(4);
    expect(settles.visible(B.id), "history-free, B's box is clear at rest").toBe(true);
    settles.unmount();
    // A scene that never settles: hidden B never earns its box back by the margin.
    const never = mountLabels();
    at(never, "covered", 0);
    flush(30);
    expect(never.visible(B.id), "B on A is hidden").toBe(false);
    at(never, "rest", 1);
    flush(40);
    expect(never.visible(B.id), "by the hidden margin B stays out at rest (so the two passes disagree)").toBe(false);
    never.unmount();
  });

  it("a name that left in a move shorter than the dwell does not blink back when the scene settles", () => {
    const log: boolean[] = [];
    const h = mountLabels(cooperative(log));
    const t = timeline(h);
    h.unmount();
    expect(t[39], "precondition: B was on screen before the move").toBe(true);
    expect(t.slice(40, 43).includes(false), "precondition: B left during the move").toBe(true);
    expect(blinks(t)).toEqual([]);
    // It still comes back, once the reversal is no longer a blink: the final set is history-free.
    expect(t[t.length - 1], "B never came back at rest").toBe(true);
    // And the report settles: a layer that reports "converging" forever would hold every capture.
    expect(log[log.length - 1], "the layer still reports converging at rest").toBe(false);
  });

  it("a forced name never holds the settle: selecting a host that comes into view reports nothing to wait for", () => {
    /* The settled pass shows an urgent name exactly as a moving pass does, so a forced name's young
       verdict is not a reversal waiting to happen — counting it would delay every capture after a
       selection by the whole dwell for nothing. */
    const log: boolean[] = [];
    const h = mountLabels(cooperative(log));
    h.proj.set(A.id, { x: A_X, y: ROW_Y, visible: true });
    h.proj.set(B.id, { x: APART_X, y: ROW_Y, visible: false });
    h.proj.set(C.id, { x: C_X, y: ROW_Y, visible: true });
    flush(40);
    expect(log[log.length - 1], "precondition: at rest, nothing to wait for").toBe(false);
    h.rerender(B.id);
    h.proj.set(B.id, { x: APART_X, y: ROW_Y, visible: true });
    flush(3);
    expect(h.visible(B.id), "precondition: the selected name shows").toBe(true);
    expect(log[log.length - 1], "a forced name held the settle").toBe(false);
    h.unmount();
  });
});

