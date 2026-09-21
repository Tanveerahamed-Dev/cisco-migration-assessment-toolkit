/**
 * Fabric3D.test.tsx — the React/three.js boundary, tested as a contract.
 *
 * `./scene` is mocked: the assertion here is never "the picture is right", it is "the scene handle
 * was built once, driven with the right imperative calls, and released". The failure this file
 * exists to catch is the silent one — a second WebGL context created by StrictMode's double-invoke
 * and never disposed, which costs a context per mount and shows up as a black canvas on the fourth
 * navigation, long after the change that caused it.
 */
import { act, StrictMode, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { failureImpact } from "../analysis/blast";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Flow, Trace } from "../core/types";

import type { FabricScene, PickResult, SceneCallbacks, SceneOptions } from "./contract";
// vi.mock is hoisted above this import, so the component under test resolves the mocked scene.
import { Fabric3D } from "./Fabric3D";

interface SceneRecord {
  canvas: HTMLCanvasElement;
  opts: SceneOptions;
  cb: SceneCallbacks;
  scene: FabricScene | null;
  disposed: number;
  calls: unknown[][];
}

interface MockState {
  scenes: SceneRecord[];
  projections: Map<string, { x: number; y: number; visible: boolean }>;
  pickResult: PickResult | null;
  /** Simulates a machine with no usable WebGL context. */
  failCreate: boolean;
  /**
   * What the mocked handle reports from `stats()`.
   *
   * The diagnostic half of the stats — `overBudget`, `drawCallBudget`, `activeOutlines` — is
   * declared on `FabricSceneEx`, not on the frozen contract, and is the half the HUD reads. A
   * standing draw-call breach was live in the shipped product with no way to see it, so the
   * surfacing gets its own test rather than a manual look.
   */
  stats: {
    quality: "high" | "balanced" | "low";
    drawCalls: number;
    drawCallBudget: number;
    activeOutlines: number;
    overBudget: boolean;
  };
}

const DEFAULT_STATS: MockState["stats"] = {
  quality: "high",
  drawCalls: 74,
  drawCallBudget: 88,
  activeOutlines: 0,
  overBudget: false,
};

const mock = vi.hoisted((): MockState => {
  return {
    scenes: [],
    projections: new Map(),
    pickResult: null,
    failCreate: false,
    stats: { quality: "high", drawCalls: 74, drawCallBudget: 88, activeOutlines: 0, overBudget: false },
  };
});

vi.mock("./scene", () => ({
  createScene: (canvas: HTMLCanvasElement, opts: SceneOptions, cb: SceneCallbacks): FabricScene => {
    if (mock.failCreate) throw new Error("WebGL context unavailable");
    const rec: SceneRecord = { canvas, opts, cb, scene: null, disposed: 0, calls: [] };
    const log =
      (name: string) =>
      (...args: unknown[]) => {
        rec.calls.push([name, ...args]);
      };
    const scene: FabricScene = {
      setData: log("setData"),
      setSelection: log("setSelection"),
      setHover: log("setHover"),
      setHighlight: log("setHighlight"),
      setTrace: log("setTrace"),
      focusDevice: log("focusDevice"),
      resetCamera: log("resetCamera"),
      setTheme: log("setTheme"),
      setQuality: log("setQuality"),
      resize: log("resize"),
      pick: () => mock.pickResult,
      project: (id: string) => mock.projections.get(id) ?? null,
      stats: () => ({
        fps: 60,
        frameMs: 16,
        triangles: 0,
        programs: 0,
        converged: true,
        /* The widened half. The real scene reports these; the contract does not declare them, which
           is exactly how a standing breach stayed invisible. */
        worstFrameMs: 16,
        qualityReasons: [],
        qualityAuto: true,
        missingTokens: [],
        undrawnHops: [],
        labelsShown: 0,
        labelsTotal: 0,
        ...mock.stats,
      }),
      dispose: () => {
        rec.disposed += 1;
      },
    };
    rec.scene = scene;
    mock.scenes.push(rec);
    return scene;
  },
}));

/* ── deterministic frame control ───────────────────────────────────────────── */

let frames = new Map<number, FrameRequestCallback>();
let nextFrameId = 1;

const flushFrames = (count = 1): void => {
  for (let i = 0; i < count; i += 1) {
    const batch = [...frames.values()];
    frames = new Map();
    for (const cb of batch) cb(0);
  }
};

interface Mounted {
  container: HTMLElement;
  root: Root;
  canvas(): HTMLCanvasElement | null;
  unmount(): void;
}

function mount(el: ReactElement): Mounted {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(el);
  });
  return {
    container,
    root,
    canvas: () => container.querySelector("canvas"),
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

const press = (el: Element, key: string): void => {
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
};

const lastScene = (): SceneRecord => {
  const rec = mock.scenes[mock.scenes.length - 1];
  if (!rec) throw new Error("no scene was created");
  return rec;
};

const callsOf = (rec: SceneRecord, name: string): unknown[][] =>
  rec.calls.filter((c) => c[0] === name);

beforeEach(() => {
  mock.scenes = [];
  mock.projections = new Map();
  mock.pickResult = null;
  mock.failCreate = false;
  mock.stats = { ...DEFAULT_STATS };
  frames = new Map();
  nextFrameId = 1;
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    const id = nextFrameId;
    nextFrameId += 1;
    frames.set(id, cb);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    frames.delete(id);
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  useInvestigation.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useInvestigation.getState().reset();
});

/* ── lifetime ──────────────────────────────────────────────────────────────── */

describe("scene lifetime", () => {
  it("creates exactly one scene per mount and disposes it exactly once", () => {
    const m = mount(<Fabric3D />);
    expect(mock.scenes).toHaveLength(1);
    expect(lastScene().disposed).toBe(0);
    expect(m.canvas()).not.toBeNull();

    m.unmount();
    expect(mock.scenes).toHaveLength(1);
    expect(mock.scenes[0]?.disposed).toBe(1);
  });

  it("disposes every scene exactly once under StrictMode's double-invoke", () => {
    const m = mount(
      <StrictMode>
        <Fabric3D />
      </StrictMode>,
    );

    // React 19 mounts effects, tears them down, and mounts them again. Two scenes is correct; two
    // LIVE scenes is the leak.
    expect(mock.scenes.length).toBeGreaterThanOrEqual(2);
    const live = mock.scenes.filter((s) => s.disposed === 0);
    expect(live).toHaveLength(1);
    // A disposed scene's canvas must leave the DOM: a canvas whose context was released can never
    // be reused, so a leftover element is a dead surface sitting in the layout.
    expect(m.container.querySelectorAll("canvas")).toHaveLength(1);
    expect(live[0]?.canvas).toBe(m.canvas());

    m.unmount();
    expect(mock.scenes.every((s) => s.disposed === 1)).toBe(true);
    expect(m.container.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("drives store changes through imperative calls instead of rebuilding the scene", () => {
    const m = mount(<Fabric3D />);
    const rec = lastScene();
    const before = mock.scenes.length;

    act(() => {
      useInvestigation.getState().selectDevice("core1");
    });
    act(() => {
      useInvestigation.getState().setQuery("band:Poor");
    });

    expect(mock.scenes).toHaveLength(before);
    expect(callsOf(rec, "setSelection").at(-1)).toEqual(["setSelection", "core1", null]);
    expect(callsOf(rec, "setHighlight").length).toBeGreaterThan(0);
    // setData is the replace-the-topology verb; an unchanged fabric must never pay for it.
    expect(callsOf(rec, "setData")).toHaveLength(0);

    m.unmount();
  });

  it("routes a trace and its active hop to setTrace", () => {
    const m = mount(<Fabric3D />);
    const rec = lastScene();
    const flow: Flow = {
      srcIp: "10.20.10.5",
      dstIp: "10.20.30.9",
      protocol: "tcp",
      dstPort: 443,
      srcPort: null,
    };
    const trace: Trace = {
      flow,
      outcome: "indeterminate",
      hops: [
        {
          index: 0,
          host: "core1",
          outIntf: null,
          nextHost: "core2",
          nextHop: null,
          verdict: "unmodeled",
          decidedBy: null,
          evidence: [],
          alternatives: [],
        },
      ],
      claim: "test",
      caveats: ["test"],
      unmodelledHosts: ["core2"],
      elapsedMs: 1,
    };

    act(() => {
      useInvestigation.getState().setTrace(trace);
    });

    expect(callsOf(rec, "setTrace").at(-1)).toEqual(["setTrace", trace, 0]);
    /* An unmodelled hop is NOT a blocked hop. It used to be routed into `blockedHost`, which is the
       scene's alarm channel and therefore an assertion that this host stopped the packet — the
       engine explicitly declined to assert that. It reaches the fabric as the trace's ending
       (setTrace already carries the hop and its verdict) and is marked in words by the label
       layer; see the three-endings tests below. */
    const highlight = callsOf(rec, "setHighlight").at(-1)?.[1] as { blockedHost: string | null } | null;
    expect(highlight === null || highlight.blockedHost === null).toBe(true);

    m.unmount();
  });
});

/* ── keyboard ──────────────────────────────────────────────────────────────── */

describe("keyboard operation", () => {
  const layout = () => {
    mock.projections.set("core1", { x: 100, y: 100, visible: true });
    mock.projections.set("core2", { x: 200, y: 100, visible: true });
    mock.projections.set("dist1", { x: 100, y: 200, visible: true });
  };

  it("moves the selection to the nearest neighbour in the pressed direction", () => {
    layout();
    const m = mount(<Fabric3D />);
    const canvas = m.canvas();
    expect(canvas).not.toBeNull();

    act(() => {
      useInvestigation.getState().selectDevice("core1");
    });

    press(canvas!, "ArrowRight");
    expect(useInvestigation.getState().deviceId).toBe("core2");

    act(() => {
      useInvestigation.getState().selectDevice("core1");
    });
    press(canvas!, "ArrowDown");
    expect(useInvestigation.getState().deviceId).toBe("dist1");

    m.unmount();
  });

  it("enters the fabric at the node nearest the centre when nothing is selected", () => {
    layout();
    const m = mount(<Fabric3D />);
    press(m.canvas()!, "ArrowRight");
    expect(useInvestigation.getState().deviceId).toBe("core1");
    m.unmount();
  });

  it("frames the camera on Enter and clears the selection on Escape", () => {
    layout();
    const m = mount(<Fabric3D />);
    const rec = lastScene();

    act(() => {
      useInvestigation.getState().selectDevice("core2");
    });
    press(m.canvas()!, "Enter");
    expect(callsOf(rec, "focusDevice").at(-1)).toEqual(["focusDevice", "core2"]);

    press(m.canvas()!, "Escape");
    expect(useInvestigation.getState().deviceId).toBeNull();

    press(m.canvas()!, "Home");
    expect(callsOf(rec, "resetCamera").length).toBeGreaterThan(0);

    m.unmount();
  });

  it("announces the selection, naming unobserved fields as unobserved", () => {
    const m = mount(<Fabric3D />);
    act(() => {
      useInvestigation.getState().selectDevice("AP-floor1");
    });
    const status = m.container.querySelector('[role="status"]');
    expect(status?.textContent).toContain("AP-floor1");
    expect(status?.textContent).toContain("never collected");
    expect(status?.textContent).toContain("not observed");
    m.unmount();
  });
});

/* ── the non-canvas equivalent ─────────────────────────────────────────────── */

describe("fabric tree", () => {
  it("exposes every device in the snapshot as a treeitem", () => {
    const m = mount(<Fabric3D />);
    const rows = m.container.querySelectorAll('[data-testid="fabric3d-tree-device"]');
    const ids = new Set([...rows].map((r) => r.getAttribute("data-target")));
    expect(rows).toHaveLength(fabric.devices.length);
    for (const d of fabric.devices) expect(ids.has(d.id)).toBe(true);
    m.unmount();
  });

  it("selects the same store state the canvas does", () => {
    const m = mount(<Fabric3D />);
    const row = m.container.querySelector('[data-target="core1"]');
    expect(row).not.toBeNull();
    act(() => {
      (row as HTMLElement).click();
    });
    expect(useInvestigation.getState().deviceId).toBe("core1");
    m.unmount();
  });

  it("becomes the view when the renderer cannot start, and says why", () => {
    mock.failCreate = true;
    const m = mount(<Fabric3D />);

    const alert = m.container.querySelector('[data-testid="fabric3d-fallback"]');
    expect(alert?.textContent).toContain("WebGL context unavailable");
    // A dead renderer must not leave a blank canvas behind that reads as an empty network.
    expect(m.canvas()).toBeNull();
    expect(m.container.querySelector('[data-testid="fabric3d-tree"]')?.getAttribute("data-hidden")).toBe(
      "false",
    );
    expect(m.container.querySelectorAll('[data-testid="fabric3d-tree-device"]')).toHaveLength(
      fabric.devices.length,
    );

    m.unmount();
  });

  it("states the unobserved denominators rather than implying completeness", () => {
    const m = mount(<Fabric3D />);
    const foot = m.container.querySelector(".fabric3d__tree-foot");
    const uncollected = fabric.devices.filter((d) => !d.collected).length;
    const unmeasured = fabric.links.filter((l) => l.isBridge === null).length;
    expect(foot?.textContent).toContain(`${uncollected} not collected`);
    expect(foot?.textContent).toContain(`${unmeasured} links have no centrality measurement`);
    m.unmount();
  });
});

/* ── labels ────────────────────────────────────────────────────────────────── */

describe("labels", () => {
  it("does not render a label for an occluded anchor", () => {
    mock.projections.set("core1", { x: 40, y: 40, visible: true });
    mock.projections.set("core2", { x: 300, y: 300, visible: false });
    const m = mount(<Fabric3D />);
    flushFrames();

    const visible = m.container.querySelector('[data-device="core1"]');
    const occluded = m.container.querySelector('[data-device="core2"]');
    expect(visible?.getAttribute("data-visible")).toBe("true");
    expect(occluded?.getAttribute("data-visible")).toBe("false");

    m.unmount();
  });

  it("drops a colliding label but never the selected one", () => {
    // Two anchors on the same point: exactly one may survive the declutter, and it must be the
    // node the user selected.
    mock.projections.set("core1", { x: 120, y: 120, visible: true });
    mock.projections.set("core2", { x: 120, y: 120, visible: true });
    const m = mount(<Fabric3D />);

    act(() => {
      useInvestigation.getState().selectDevice("core2");
    });
    flushFrames();

    expect(m.container.querySelector('[data-device="core2"]')?.getAttribute("data-visible")).toBe(
      "true",
    );
    expect(m.container.querySelector('[data-device="core1"]')?.getAttribute("data-visible")).toBe(
      "false",
    );

    m.unmount();
  });

  it("stops its frame loop when the stage unmounts", () => {
    mock.projections.set("core1", { x: 40, y: 40, visible: true });
    const m = mount(<Fabric3D />);
    flushFrames();
    m.unmount();
    const pendingAfterUnmount = frames.size;
    flushFrames();
    // Nothing may re-arm a frame after teardown; a loop that survives its component is a leak that
    // keeps a disposed scene handle alive.
    expect(frames.size).toBeLessThanOrEqual(pendingAfterUnmount);
    expect(frames.size).toBe(0);
  });
});

/* ── re-aiming and label placement (acceptance A4, A5) ─────────────────────── */

describe("re-aiming", () => {
  it("places a label at the scene's canvas-space projection, not one canvas origin away", () => {
    /* scene.project() reports CANVAS-relative CSS pixels, and this overlay is positioned against
       the canvas box. The loop therefore must NOT subtract the container origin a second time.
       It did: the label layer defaulted to coordinateSpace "client", reasoning from pick() (which
       takes client coordinates as an INPUT) to project() (which returns canvas coordinates as an
       OUTPUT). Measured on the live app at 1920x1080, every one of the 26 hostnames was drawn
       dx=-340, dy=-119 from the chassis it named — over a different switch, under the legend and
       out past the left rail.
       The stubbed rect below is the real measured canvas box, so this test fails by exactly that
       displacement if the double subtraction ever returns. */
    mock.projections.set("core1", { x: 500, y: 400, visible: true });
    const m = mount(<Fabric3D />);
    const overlay = m.container.querySelector<HTMLElement>('[data-testid="fabric3d-labels"]');
    if (overlay === null) throw new Error("the label overlay did not render");
    overlay.getBoundingClientRect = (): DOMRect =>
      ({
        left: 340, top: 92, right: 1500, bottom: 1054,
        width: 1160, height: 962, x: 340, y: 92,
        toJSON: () => ({}),
      }) as DOMRect;
    flushFrames();

    const el = m.container.querySelector<HTMLElement>('[data-device="core1"]');
    expect(el?.dataset["visible"]).toBe("true");
    expect(el?.style.transform).toBe("translate3d(500px, 400px, 0) translate(-50%, -160%)");

    m.unmount();
  });

  it("emphasises a selected finding's devices without moving the camera", () => {
    /* A4: the fabric is the surface that answers "where in the network is this?", so selecting a
       finding has to change it. findingId was not an input to the highlight memo at all, so the
       canvas rendered byte-identical pixels before and after a finding selection (measured: sha
       c00b1e7ef097448f both times) and the fabric could not locate a finding.
       Emphasis only — resetCamera/focusDevice must stay untouched, because re-aiming is not a
       flight and a queue click must not throw away the pose the reader is working in. */
    const finding = fabric.findings.find((f) => f.devices.length > 0);
    if (finding === undefined) throw new Error("this snapshot has no finding naming a device");
    const expected = fabric.devices
      .filter((d) => finding.devices.includes(d.host) || finding.devices.includes(d.id))
      .map((d) => d.id);
    expect(expected.length).toBeGreaterThan(0);

    const m = mount(<Fabric3D />);
    const rec = lastScene();

    act(() => {
      useInvestigation.getState().selectFinding(finding.id);
    });

    const highlight = callsOf(rec, "setHighlight").at(-1)?.[1] as { hosts: string[] } | null;
    expect(highlight).not.toBeNull();
    for (const id of expected) expect(highlight?.hosts).toContain(id);
    expect(callsOf(rec, "resetCamera")).toHaveLength(0);
    expect(callsOf(rec, "focusDevice")).toHaveLength(0);

    m.unmount();
  });
});

/* ── the legend does not paint over the topology on a first visit ──────────── */

describe("fabric legend", () => {
  it("is closed by default and offers a visible control instead", () => {
    /* Measured at 1920x1080: open, the legend is an opaque 175x930 overlay covering 14.6% of the
       1160x962 canvas, docked over the left edge of the stage where core2, access17, access3,
       access5 and access10 render — so a first visit showed a partially occluded topology with
       labels truncated to "re2", "ccess17", "ccess3", "ss5" and "s10", while stats() still
       reported labelsShown 26 of 26.
       Closed-by-default costs one click and hides nothing, because the collapsed state is a
       permanently visible control. Both halves are asserted: "closed" alone would be satisfied by
       a legend with no way back. */
    window.localStorage.removeItem("atlas-scope.fabric-legend.open");
    const m = mount(<Fabric3D />);

    expect(m.container.querySelector('[data-testid="fabric3d-legend"]')).toBeNull();
    const show = m.container.querySelector('[data-testid="fabric3d-legend-show"]');
    expect(show).not.toBeNull();
    expect(show?.textContent?.trim()).toBe("Legend");

    m.unmount();
  });

  it("still honours an explicit stored preference to keep it open", () => {
    window.localStorage.setItem("atlas-scope.fabric-legend.open", "1");
    const m = mount(<Fabric3D />);
    expect(m.container.querySelector('[data-testid="fabric3d-legend"]')).not.toBeNull();
    m.unmount();
    window.localStorage.removeItem("atlas-scope.fabric-legend.open");
  });
});

/* ── the quality chip: degradation is explicit, never silent ───────────────── */

describe("a standing draw-call breach is visible in the product", () => {
  /**
   * WHY THIS EXISTS. The scene has always set an internal `overBudget` flag, and for the whole of
   * the path-trace surface it was permanently true: a converged frame cost 141 draw calls against a
   * flat ceiling of 120, on every frame, in every path state. It was unreachable. No UI read it, it
   * was not on the `SceneStats` the frozen contract declares, and the only report was a
   * `console.error` behind `import.meta.env.DEV` — absent from every shipped chunk. The product
   * breached its own published budget in front of the user and said nothing.
   *
   * So the surfacing is tested, not looked at once. Both paths run here: a clean frame must NOT
   * mark the chip (a warning that is always on is not a warning), and a breaching frame must say
   * the numbers out loud.
   */
  const chip = (m: Mounted): HTMLElement => {
    const el = m.container.querySelector(".fabric3d__quality");
    if (!(el instanceof HTMLElement)) throw new Error("no quality chip rendered");
    return el;
  };

  /** Drive one `stats` event through the real callback the scene would use. */
  const emitStats = (): void => {
    const rec = lastScene();
    act(() => {
      rec.cb.onEvent({ type: "stats", stats: rec.scene!.stats() });
    });
  };

  it("says nothing when the frame is inside its budget", () => {
    mock.stats = { quality: "high", drawCalls: 74, drawCallBudget: 88, activeOutlines: 0, overBudget: false };
    const m = mount(<Fabric3D />);
    emitStats();

    const el = chip(m);
    expect(el.getAttribute("data-over-budget")).toBe("false");
    expect(el.getAttribute("data-degraded")).toBe("false");
    expect(el.textContent).toContain("Quality high");
    expect(el.textContent).not.toContain("draw calls");
    m.unmount();
  });

  it("names the cost, the ceiling and why it is standing when the frame is over budget", () => {
    // The real measurement from the state this defect was found in: a denied path trace at `high`,
    // two outline effects active. The numbers are the product's, not the test's invention.
    mock.stats = { quality: "high", drawCalls: 141, drawCallBudget: 120, activeOutlines: 2, overBudget: true };
    const m = mount(<Fabric3D />);
    emitStats();

    const el = chip(m);
    expect(el.getAttribute("data-over-budget")).toBe("true");
    // Marked as degraded too: a frame costing more than the design budgets for is not a healthy one.
    expect(el.getAttribute("data-degraded")).toBe("true");
    expect(el.textContent).toContain("141/120 draw calls");
    const title = el.getAttribute("title") ?? "";
    expect(title).toContain("141");
    expect(title).toContain("120");
    expect(title).toContain("2 outline effect(s)");
    // The transient/standing distinction is the whole reason the flag takes two frames to set.
    expect(title).toContain("not a one-off rebuild");
    m.unmount();
  });

  it("clears the mark when the breach stops, so the warning stays informative", () => {
    mock.stats = { quality: "high", drawCalls: 141, drawCallBudget: 120, activeOutlines: 2, overBudget: true };
    const m = mount(<Fabric3D />);
    emitStats();
    expect(chip(m).getAttribute("data-over-budget")).toBe("true");

    mock.stats = { quality: "high", drawCalls: 74, drawCallBudget: 88, activeOutlines: 0, overBudget: false };
    emitStats();
    expect(chip(m).getAttribute("data-over-budget")).toBe("false");
    expect(chip(m).textContent).not.toContain("draw calls");
    m.unmount();
  });

  it("reports a reduced tier and a breach as two different things", () => {
    // They are both "this frame is not what the design specifies" and they have different causes.
    // Collapsing them into one word would leave a reader guessing which one happened.
    mock.stats = { quality: "low", drawCalls: 74, drawCallBudget: 88, activeOutlines: 0, overBudget: false };
    const m = mount(<Fabric3D />);
    emitStats();
    const el = chip(m);
    expect(el.getAttribute("data-degraded")).toBe("true");
    expect(el.getAttribute("data-over-budget")).toBe("false");
    expect(el.textContent).toContain("Quality low");
    m.unmount();
  });
});

/* ── blast radius, drawn rather than only listed (acceptance A6) ───────────── */

describe("the blast radius reaches the fabric", () => {
  /** The same analysis the Inspector reads, so the test cannot drift from the product. */
  const strandedBy = (host: string): string[] => failureImpact(host).newlyStranded;

  /** An articulation point with a non-empty blast radius, chosen FROM THE DATA, not typed here. */
  const cutPoint = fabric.devices.map((d) => d.host).find((h) => strandedBy(h).length > 0);
  /** A device whose failure partitions nothing — the control. */
  const quiet = fabric.devices.map((d) => d.host).find((h) => strandedBy(h).length === 0);

  const projectAll = (): void => {
    // Spread out, so the declutter drops nothing and the marks can be counted.
    fabric.devices.forEach((d, i) => {
      mock.projections.set(d.id, { x: 40 + (i % 6) * 260, y: 40 + Math.floor(i / 6) * 180, visible: true });
    });
  };

  it("marks the cut point and every host it strands, and lifts them out of the dimmed field", () => {
    expect(cutPoint, "this snapshot must hold at least one articulation point").toBeDefined();
    const stranded = strandedBy(cutPoint!);
    projectAll();
    const m = mount(<Fabric3D />);
    const rec = lastScene();

    act(() => useInvestigation.getState().selectDevice(cutPoint!));
    flushFrames(2);

    const label = m.container.querySelector(`[data-device="${cutPoint!}"]`);
    expect(label?.getAttribute("data-cut"), "the cut point says so in a word, not a colour").toBe(
      "yes",
    );
    for (const host of stranded) {
      const el = m.container.querySelector(`[data-device="${host}"]`);
      expect(el?.getAttribute("data-stranded"), `${host} is stranded and must say so`).toBe("yes");
    }

    /* Before this, `HighlightState.hosts` was built from the filters and the selected finding and
       from nothing else, so the nine stranded hosts were rendered exactly like every other node. */
    const highlight = callsOf(rec, "setHighlight").at(-1)?.[1] as { hosts: string[] } | null;
    expect(highlight, "a blast radius must produce a highlight").not.toBeNull();
    for (const host of stranded) expect(highlight!.hosts).toContain(host);

    m.unmount();
  });

  it("marks nothing when the selected device partitions nothing", () => {
    expect(quiet).toBeDefined();
    projectAll();
    const m = mount(<Fabric3D />);

    act(() => useInvestigation.getState().selectDevice(quiet!));
    flushFrames(2);

    expect(m.container.querySelectorAll('[data-cut="yes"]')).toHaveLength(0);
    expect(m.container.querySelectorAll('[data-stranded="yes"]')).toHaveLength(0);

    m.unmount();
  });

  it("never prints `blocked` on a host carrying a delivered flow", () => {
    /* THE REGRESSION THIS FILE EXISTS FOR. The scene contract gives ONE alarm field to two
       different claims — "this hop stopped the packet" and "this is the element whose failure is
       being projected". Routing the blast radius through it put the word BLOCKED on core1 while a
       flow was being delivered THROUGH core1, because core1 is also a cut point. A conditional
       must never be printed with a fact's word. */
    expect(cutPoint).toBeDefined();
    const flow: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null };
    const delivered: Trace = {
      flow,
      outcome: "delivered",
      hops: [
        {
          index: 0,
          host: cutPoint!,
          outIntf: "Vlan30",
          nextHost: null,
          nextHop: null,
          verdict: "delivered",
          decidedBy: null,
          evidence: [],
          alternatives: [],
        },
      ],
      claim: "test",
      caveats: ["test"],
      unmodelledHosts: [],
      elapsedMs: 1,
    };
    projectAll();
    const m = mount(<Fabric3D />);

    act(() => {
      useInvestigation.getState().selectDevice(cutPoint!);
      useInvestigation.getState().setTrace(delivered);
    });
    flushFrames(2);

    expect(m.container.querySelectorAll('[data-alarm="blocked"]')).toHaveLength(0);
    const label = m.container.querySelector(`[data-device="${cutPoint!}"]`);
    /* BOTH claims, on their own channels. The trace's ending is a fact about this packet; the cut
       point is a projection about a failure that has not happened. While they shared one slot the
       winner erased the loser, so this host could state only one of the two true things about it. */
    expect(label?.getAttribute("data-alarm")).toBe("delivered");
    expect(label?.getAttribute("data-cut")).toBe("yes");

    m.unmount();
  });

  it("gives the blocked hop of a denied flow the alarm word, and the halo channel", () => {
    const denied: Trace = {
      flow: { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null },
      outcome: "dropped",
      hops: [
        {
          index: 0,
          host: "core1",
          outIntf: null,
          nextHost: null,
          nextHop: null,
          verdict: "denied",
          decidedBy: null,
          evidence: [],
          alternatives: [],
        },
      ],
      claim: "test",
      caveats: ["test"],
      unmodelledHosts: [],
      elapsedMs: 1,
    };
    projectAll();
    const m = mount(<Fabric3D />);
    const rec = lastScene();

    act(() => useInvestigation.getState().setTrace(denied));
    flushFrames(2);

    expect(m.container.querySelector('[data-device="core1"]')?.getAttribute("data-alarm")).toBe("blocked");
    const highlight = callsOf(rec, "setHighlight").at(-1)?.[1] as { blockedHost: string | null };
    expect(highlight.blockedHost, "the halo channel stays the trace's").toBe("core1");

    m.unmount();
  });

  /* ── the three endings ────────────────────────────────────────────────────
   *
   * THE DEFECT THESE EXIST FOR. The fabric had two states for a trace and the model has three. An
   * indeterminate hop was drawn with the denied treatment AND the denied word: measured on the
   * release build, the stage clip for `icmp 10.0.10.50 -> 10.0.30.10` (undecidable, because
   * `acls.core1.PROTECT_SERVERS[2]` carries an unmodellable icmp_type qualifier) was
   * BYTE-IDENTICAL to the clip for `tcp/3389` (genuinely denied) — sha256
   * cefadc6d1e19d0fe… for both — while the side panel for the same trace said INDETERMINATE.
   * The predecessor of this test pinned `blockedHost === 'core1'` for an unmodelled hop and never
   * looked at the printed word, so the overclaim was invisible to the suite.
   *
   * The assertions below are on the WORD, because the word is the claim.
   */

  /** The word the label is actually printing, read through the attribute that selects it. */
  const alarmWord = (m: Mounted, device: string): string | null => {
    const label = m.container.querySelector(`[data-device="${device}"]`);
    const kind = label?.getAttribute("data-alarm") ?? "";
    if (kind === "") return null;
    const mark = label?.querySelector(`.fabric3d-label__alarm--${kind}`);
    return mark === null || mark === undefined ? null : mark.textContent!.replace(/\s+/g, " ").trim();
  };

  const traceOf = (verdict: Trace["hops"][number]["verdict"], outcome: Trace["outcome"]): Trace => ({
    flow: { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "icmp", dstPort: null, srcPort: null },
    outcome,
    hops: [
      {
        index: 0,
        host: "core1",
        outIntf: null,
        nextHost: null,
        nextHop: null,
        verdict,
        decidedBy: null,
        evidence: [],
        alternatives: [],
      },
    ],
    claim: "test",
    caveats: ["test"],
    unmodelledHosts: verdict === "unmodeled" ? ["core1"] : [],
    elapsedMs: 1,
  });

  it("says `undecided`, not `blocked`, for a hop the engine declined to decide", () => {
    projectAll();

    const denied = mount(<Fabric3D />);
    const deniedScene = lastScene();
    act(() => useInvestigation.getState().setTrace(traceOf("denied", "denied")));
    flushFrames(2);
    const deniedWord = alarmWord(denied, "core1");
    const deniedHighlight = callsOf(deniedScene, "setHighlight").at(-1)?.[1] as {
      blockedHost: string | null;
    } | null;
    denied.unmount();

    const undecided = mount(<Fabric3D />);
    const undecidedScene = lastScene();
    act(() => useInvestigation.getState().setTrace(traceOf("unmodeled", "indeterminate")));
    flushFrames(2);
    const undecidedWord = alarmWord(undecided, "core1");
    const undecidedHighlight = callsOf(undecidedScene, "setHighlight").at(-1)?.[1] as {
      blockedHost: string | null;
    } | null;
    undecided.unmount();

    expect(deniedWord).toBe("✕ blocked");
    expect(undecidedWord).toBe("? undecided");
    expect(undecidedWord, "an undecided hop may not be printed with a denied hop's word").not.toBe(
      deniedWord,
    );

    /* And the canvas channel differs too, which is what makes the two captures non-identical: the
       alarm outline is an assertion that this host stopped the packet, so only the REFUTED hop
       gets it. A test that pinned the word alone would pass on a fabric that still painted the two
       states with the same pixels. */
    expect(deniedHighlight?.blockedHost).toBe("core1");
    expect(undecidedHighlight === null || undecidedHighlight.blockedHost === null).toBe(true);
  });

  it("marks a delivered hop even when that host is already the selection", () => {
    /* Measured before this existed: /?s=fabric&d=core1 and the same URL plus the delivered flow
       produced stage captures with meanDiff 0 and changedPct 0 — the successful trace coincided
       exactly with the selection treatment, so the only evidence it had run was in the side list.
       That is the split A5 is written to prevent. */
    projectAll();
    const m = mount(<Fabric3D />);

    act(() => useInvestigation.getState().selectDevice("core1"));
    flushFrames(2);
    const beforeAlarm = m.container.querySelector('[data-device="core1"]')?.getAttribute("data-alarm");

    act(() => useInvestigation.getState().setTrace(traceOf("delivered", "delivered")));
    flushFrames(2);

    expect(beforeAlarm, "no trace, no trace mark").toBe("");
    expect(alarmWord(m, "core1"), "a resolved hop carries a mark of its own").toBe("✓ delivered here");
    expect(m.container.querySelectorAll('[data-alarm="blocked"]')).toHaveLength(0);

    m.unmount();
  });
});
