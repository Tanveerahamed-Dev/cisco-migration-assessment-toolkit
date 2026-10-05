/**
 * flow-triggers.test.ts — WHAT starts the trace's draw-on and its packet loop, and what does not
 * (acceptance C6).
 *
 * THE DEFECT (independent refuter, C6, 2026-10-03): stepping hops (`]` / `[`, or a hop-list row)
 * restarted the product's one bounded loop. Fabric3D.tsx re-sends `setTrace(trace, hopIndex)` on
 * every hop change, and the overlay's `setTrace` re-armed the 240 ms draw-on and the three 1600 ms
 * packet loops unconditionally — so a reader stepping through a trace bought another ~4.8 s of
 * looping per key press (alternating `]` and `[` every 1.5 s kept the canvas moving for 14 s), while
 * the motion inventory said a hop step "never re-runs the draw-on" and the packet "stops after 3
 * loops". The "resting position" a hop step was said to steer was overwritten on the next frame and
 * hidden after the loops: never on screen.
 *
 * ROUND 2 (independent refuter, 2026-10-03): the first repair compared the Trace OBJECT, and every
 * "hop step" case here re-sent that identical object — the implementation's own definition, so the
 * tests agreed with it by construction. Browser Back / Forward across a hop step hand over a NEW
 * object of the SAME answer (`traceFlow` again), which the object test took for a new trace: the
 * draw-on and all three loops re-ran on every history step.
 *
 * THE RULE THESE TESTS HOLD: the draw-on and the packet loop are started by a NEW PICTURE — a trace
 * whose drawn path, gaps and ending differ from what the overlay is drawing, by content — and by
 * nothing else. Re-sending the trace already drawn (every hop step), or a distinct object of the same
 * answer (a history step, a re-run), changes nothing on the overlay and owes no frame; every different
 * path, and a trace drawn again after it was cleared, draws on. Under reduced motion a new picture is
 * drawn complete and the packet never runs.
 *
 * The traces are the REAL producer's (`traceFlow` over the compiled snapshot, every suggested flow and
 * a sweep) drawn over the REAL cables; the class is every one of them the overlay draws a path for.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera } from "three";
import type { LineMaterial } from "three/addons/lines/LineMaterial.js";
import type { Line2 } from "three/addons/lines/Line2.js";
import fabricJson from "../data/fabric.json";
import type { Device, Flow, Link, Trace } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { computeLayout } from "./layout";
import { createFlowOverlay, DRAW_ON_MS, PACKET_LOOP_MS, PACKET_LOOPS, type FlowOverlay } from "./flow";
import { readTokens } from "./materials";
import { profileFor } from "./quality";
import { buildFabricGraph, traceAnchorIn, tracePolylineIn } from "./scene";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("high") });
const source = {
  polylineBetween: (a: string, b: string) => tracePolylineIn(graph, a, b),
  anchorOf: (h: string) => traceAnchorIn(graph, h),
};
const camera = new PerspectiveCamera(45, 1.2, 1, 4000);
const FRAME = 1000 / 60;
const RUN_MS = PACKET_LOOPS * PACKET_LOOP_MS;

function flowsToTry(): Flow[] {
  const out: Flow[] = suggestedFlows().map((s) => s.flow);
  const srcs = ["10.0.40.50", "10.0.41.50", "10.0.20.50", "10.0.10.50", "10.0.30.10", "10.0.20.10"];
  const dsts = ["10.0.10.50", "10.0.30.10", "198.51.100.7", "10.0.20.10", "10.0.41.50", "10.0.40.50"];
  for (const s of srcs) for (const d of dsts) for (const p of [22, 443]) {
    if (s !== d) out.push({ srcIp: s, dstIp: d, protocol: "tcp", dstPort: p, srcPort: null });
  }
  return out;
}

/** Every real trace the overlay draws a path for: the traces a packet can run along. */
const drawable: { label: string; flow: Flow }[] = (() => {
  const seen = new Set<string>();
  const out: { label: string; flow: Flow }[] = [];
  for (const flow of flowsToTry()) {
    const t = traceFlow(flow);
    const key = t.hops.map((h) => h.host).join(">");
    if (seen.has(key)) continue;
    const o = createFlowOverlay(readTokens("dark"));
    try {
      o.setTrace(t, source);
      if (o.pathPoints().length >= 6) {
        seen.add(key);
        out.push({ label: `${flow.srcIp} -> ${flow.dstIp} ${flow.protocol}/${flow.dstPort ?? "-"} (${key})`, flow });
      }
    } finally {
      o.dispose();
    }
  }
  return out;
})();

const packetOf = (o: FlowOverlay) => o.emissiveObjects().find((x) => x.name === "trace-packet")!;
const pathMaterialOf = (o: FlowOverlay) =>
  (o.emissiveObjects().find((x) => x.name === "trace-path") as Line2).material as LineMaterial;

/** Step frames from `from` for `ms`; returns the times at which the overlay said a frame was owed. */
function run(o: FlowOverlay, from: number, ms: number): number[] {
  const owed: number[] = [];
  for (let t = from; t <= from + ms; t += FRAME) if (o.update(t, camera)) owed.push(t - from);
  return owed;
}

describe("the class is real and non-empty", () => {
  it("the real snapshot gives at least one trace with a drawn path (the refuter's dist1 -> core1 preset among them)", () => {
    expect(drawable.length).toBeGreaterThan(0);
    expect(drawable.some((d) => d.label.includes("dist1>core1"))).toBe(true);
  });
});

describe.each(drawable)("C6 triggers — $label", ({ flow }) => {
  it("a NEW trace draws on once and runs its bounded loops once, then owes nothing", () => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      expect(o.setTrace(traceFlow(flow), source), "a new trace reports itself drawn").toBe(true);
      expect(packetOf(o).visible).toBe(true);
      const owed = run(o, 1000, RUN_MS + 2000);
      expect(owed[0]).toBe(0);
      // Owed frames end with the third loop, and not one frame is owed after it.
      expect(Math.max(...owed)).toBeLessThan(RUN_MS + FRAME);
      expect(Math.max(...owed)).toBeGreaterThanOrEqual(RUN_MS - FRAME);
      expect(packetOf(o).visible).toBe(false);
    } finally {
      o.dispose();
    }
  });

  it("re-sending the trace already drawn — what every hop step does — re-runs nothing", () => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      const trace = traceFlow(flow);
      o.setTrace(trace, source);
      run(o, 1000, RUN_MS + 500);
      const full = pathMaterialOf(o).dashSize;
      // One re-send per hop the reader can step to: the call scene.ts makes for each.
      for (let hop = 0; hop < trace.hops.length; hop += 1) {
        expect(o.setTrace(trace, source), "a re-sent trace is not a new drawing").toBe(false);
        // No draw-on: the path is still drawn in full the moment the hop changes.
        expect(pathMaterialOf(o).dashSize).toBe(full);
        expect(packetOf(o).visible).toBe(false);
        expect(run(o, 10_000 + hop * 20_000, RUN_MS + 2000), `hop ${hop} owed frames`).toEqual([]);
        expect(packetOf(o).visible).toBe(false);
      }
    } finally {
      o.dispose();
    }
  });

  it("a hop step DURING the run neither restarts the draw-on nor extends the loop", () => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      const trace = traceFlow(flow);
      o.setTrace(trace, source);
      run(o, 1000, 2000);
      const full = pathMaterialOf(o).dashSize;
      expect(o.setTrace(trace, source)).toBe(false);
      expect(pathMaterialOf(o).dashSize).toBe(full);
      // The run keeps its ORIGINAL start (t = 1000): it is over at 1000 + RUN_MS, not 2000 ms later.
      const owed = run(o, 1000 + 2000 + FRAME, RUN_MS + 2000).map((t) => t + 2000 + FRAME);
      expect(Math.max(...owed)).toBeLessThan(RUN_MS + FRAME);
      expect(packetOf(o).visible).toBe(false);
    } finally {
      o.dispose();
    }
  });

  it("a re-trace of the same flow — a DISTINCT trace object with the same answer — re-runs nothing", () => {
    /* What a history Back / Forward across a hop step, an explicit re-run of the same question and a
       restore all hand the overlay: `traceFlow(flow)` again, a new object whose drawn picture is the
       one already on screen. The refuter (C6 round 2, 2026-10-03) measured Back/Forward restarting
       the draw-on and all three loops because the overlay compared object identity. */
    const o = createFlowOverlay(readTokens("dark"));
    try {
      const first = traceFlow(flow);
      o.setTrace(first, source);
      run(o, 1000, RUN_MS + 500);
      const full = pathMaterialOf(o).dashSize;
      for (let again = 0; again < 3; again += 1) {
        const same = traceFlow(flow);
        expect(same, "the producer returns a new object (the case is real)").not.toBe(first);
        expect(o.setTrace(same, source), "the same picture is not a new drawing").toBe(false);
        expect(pathMaterialOf(o).dashSize).toBe(full);
        expect(packetOf(o).visible).toBe(false);
        expect(run(o, 20_000 + again * 20_000, RUN_MS + 2000), `re-trace ${again} owed frames`).toEqual([]);
      }
    } finally {
      o.dispose();
    }
  });

  it("a re-trace DURING the run neither restarts the draw-on nor extends the loop", () => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      o.setTrace(traceFlow(flow), source);
      run(o, 1000, 2000);
      const full = pathMaterialOf(o).dashSize;
      expect(o.setTrace(traceFlow(flow), source)).toBe(false);
      expect(pathMaterialOf(o).dashSize).toBe(full);
      const owed = run(o, 1000 + 2000 + FRAME, RUN_MS + 2000).map((t) => t + 2000 + FRAME);
      expect(Math.max(...owed)).toBeLessThan(RUN_MS + FRAME);
      expect(packetOf(o).visible).toBe(false);
    } finally {
      o.dispose();
    }
  });

  it("once the trace is CLEARED, the same flow traced again is a new picture: it draws on and loops once", () => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      o.setTrace(traceFlow(flow), source);
      run(o, 1000, RUN_MS + 500);
      expect(o.setTrace(null, source)).toBe(false);
      expect(o.setTrace(traceFlow(flow), source)).toBe(true);
      expect(packetOf(o).visible).toBe(true);
      expect(pathMaterialOf(o).dashSize).toBe(0);
      const owed = run(o, 20_000, RUN_MS + 2000);
      expect(owed[0]).toBe(0);
      expect(Math.max(...owed)).toBeLessThan(RUN_MS + FRAME);
    } finally {
      o.dispose();
    }
  });

  it("under reduced motion a new trace is drawn complete, the packet never runs, and hop steps change nothing", () => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      o.setReducedMotion(true);
      const trace = traceFlow(flow);
      expect(o.setTrace(trace, source)).toBe(true);
      const full = pathMaterialOf(o).dashSize;
      expect(full).toBeGreaterThan(0);
      expect(packetOf(o).visible).toBe(false);
      expect(run(o, 1000, DRAW_ON_MS + RUN_MS)).toEqual([]);
      for (let hop = 0; hop < trace.hops.length; hop += 1) {
        expect(o.setTrace(trace, source)).toBe(false);
        expect(packetOf(o).visible).toBe(false);
        expect(pathMaterialOf(o).dashSize).toBe(full);
        expect(run(o, 20_000 + hop * 10_000, 1000)).toEqual([]);
      }
    } finally {
      o.dispose();
    }
  });
});

describe("C6 triggers — a DIFFERENT picture is a new trace, whatever drew before it", () => {
  /* The other side of the content key: it must not swallow a real change. Every ordered pair of
     drawable traces whose drawn paths differ: drawing B over A draws on, and A again over B draws on. */
  const pairs: { a: Flow; b: Flow; label: string }[] = [];
  for (const x of drawable) for (const y of drawable) if (x !== y) pairs.push({ a: x.flow, b: y.flow, label: `${x.label} then ${y.label}` });
  it.each(pairs)("$label", ({ a, b }) => {
    const o = createFlowOverlay(readTokens("dark"));
    try {
      o.setTrace(traceFlow(a), source);
      run(o, 1000, RUN_MS + 500);
      expect(o.setTrace(traceFlow(b), source), "another path is a new drawing").toBe(true);
      expect(pathMaterialOf(o).dashSize).toBe(0);
      run(o, 20_000, RUN_MS + 500);
      expect(o.setTrace(traceFlow(a), source), "and back to the first path is a new drawing again").toBe(true);
      expect(packetOf(o).visible).toBe(true);
    } finally {
      o.dispose();
    }
  });
});

describe("C6 triggers — no sequence of hop steps, re-traces and preference changes restarts the loop", () => {
  it("a seeded walk over every non-new-trace input owes no frame once the run is over", () => {
    let seed = 0x6c6;
    const rand = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };
    for (const { flow } of drawable) {
      const o = createFlowOverlay(readTokens("dark"));
      try {
        const trace: Trace = traceFlow(flow);
        o.setTrace(trace, source);
        run(o, 1000, RUN_MS + 500);
        const full = pathMaterialOf(o).dashSize;
        let t = 10_000;
        for (let step = 0; step < 60; step += 1) {
          const r = rand();
          const where = `step ${step} on ${trace.hops.map((h) => h.host).join(">")}`;
          if (r < 0.6) {
            /* The hop step (the trace re-sent) or a re-trace of the same flow (Back / Forward, a re-run):
               not one frame owed. */
            o.setTrace(r < 0.3 ? trace : traceFlow(flow), source);
            expect(run(o, t, 400), where).toEqual([]);
          } else {
            if (r < 0.75) o.setReducedMotion(rand() < 0.5);
            else if (r < 0.9) o.setResolution(800 + Math.floor(rand() * 1000), 600);
            else o.retint(readTokens(rand() < 0.5 ? "dark" : "light"));
            // A retint repaints once (the tether takes its new colour); nothing may MOVE after it.
            expect(run(o, t, 400).filter((ms) => ms > 0), where).toEqual([]);
          }
          expect(pathMaterialOf(o).dashSize, where).toBe(full);
          expect(packetOf(o).visible).toBe(false);
          t += 1000;
        }
      } finally {
        o.dispose();
      }
    }
  });
});
