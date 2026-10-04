/**
 * flow-terminal.test.ts — the three endings a trace can have, on the CANVAS.
 *
 * THE DEFECT THIS FILE EXISTS FOR. `flow.ts` divided traces in two with `outcome !== "delivered"`
 * and gave everything on the wrong side of that line the red octagonal stop alarm. So a flow the
 * engine explicitly declined to decide — `icmp 10.0.10.50 -> 10.0.30.10`, undecidable because
 * `acls.core1.PROTECT_SERVERS[2]` carries an unmodellable `icmp_type` qualifier — ended in exactly
 * the mark a genuinely denied flow ends in, in exactly the same critical red. Measured on the
 * release build before the fix: the stage capture for the undecidable flow was BYTE-IDENTICAL to
 * the capture for `tcp/3389` (sha256 cefadc6d1e19d0fe…), while the side panel for the same trace
 * said INDETERMINATE.
 *
 * The mapping is not restated here or in flow.ts: `claims.ts :: bandOfOutcome` owns it and it has
 * three values. The traces come from the REAL producer over the compiled snapshot, so a test
 * cannot agree with a renderer bug by being handed a fixture in the shape the renderer expects.
 */
import { describe, expect, it } from "vitest";

import { PerspectiveCamera, Vector3 } from "three";

import { bandOfOutcome, bandOfTrace } from "../core/claims";
import { traceFlow } from "../forwarding/engine";
import {
  createFlowOverlay,
  GLYPH_CLEARANCE,
  placeTerminalGlyph,
  STOP_GLYPH_RADIUS,
  UNDECIDED_GLYPH_RADIUS,
  type TraceSegmentSource,
} from "./flow";
import { readTokens } from "./materials";

/**
 * A straight path with real length AND enough samples near its end that the terminal-segment
 * branch is reachable: that branch keeps the last ~34 world units of the polyline and needs at
 * least two samples inside them, so a three-point line would make the assertion vacuous.
 */
const segmentSource = (): TraceSegmentSource => ({
  polylineBetween: () => {
    const pts: number[] = [];
    for (let i = 0; i <= 12; i += 1) pts.push(i * 10, 10, 0);
    return new Float32Array(pts);
  },
  anchorOf: (host: string) => ({ x: host.length * 10, y: 0, z: 0, top: 12 }),
});



/**
 * Which terminal marks are drawn for a real trace of this flow.
 *
 * `twoHop` derives a second hop FROM the producer's own hop when asked, because every trace this
 * snapshot can produce is one hop long and a one-hop trace draws no polyline at all — so the 6 px
 * terminal SEGMENT (which needs a drawn path) is unreachable on the shipped corpus. Only the
 * identity of the derived hop is invented; every other field comes from `traceFlow`. The same
 * device, and the same stated limit, as `reduced-motion.test.ts`.
 */
function terminalOf(
  flow: Parameters<typeof traceFlow>[0],
  twoHop = false,
): {
  outcome: string;
  stop: boolean;
  undecided: boolean;
  alarmSegment: boolean;
} {
  const real = traceFlow(flow);
  const first = real.hops[0];
  const trace =
    twoHop && first !== undefined
      ? {
          ...real,
          hops: [
            /* The derived hop repeats the producer's own host rather than naming another device:
               the canvas bands the trace with `bandOfTrace`, which reads every hop's evidence, and
               an invented "core2" hop imported core2's incomplete routing table into a decided
               denial and undecided it. Repeating the host adds a drawn segment and no evidence. */
            { ...first, nextHost: first.host },
            { ...first, index: 1, nextHost: null },
          ],
        }
      : real;
  const overlay = createFlowOverlay(readTokens("dark"));
  try {
    overlay.setTrace(trace, segmentSource());
    const by = (name: string) => overlay.emissiveObjects().find((o) => o.name === name);
    return {
      outcome: trace.outcome,
      stop: by("trace-stop")?.visible === true,
      undecided: by("trace-undecided")?.visible === true,
      alarmSegment: overlay.group.children.find((o) => o.name === "trace-blocked")?.visible === true,
    };
  } finally {
    overlay.dispose();
  }
}

/* The three-state tests ("RESOLVED ends in neither, REFUTED in the alarm, UNDETERMINED in the ring")
   and the band-agreement sweep moved to flow-terminal.counterfactual.test.ts on 2026-09-22: they
   were exercised on flows sourced by core1's own SVI addresses, which the engine now refuses as
   router-originated (auditor, B2), and with every remaining trace resting on an incomplete routing
   table (auditor, B1) the shipped snapshot has no RESOLVED or REFUTED trace to draw. */

describe("the terminal mark follows the TRACE band, not the outcome word (C5 critic)", () => {
  /* tcp 10.0.20.10 -> 10.0.40.50:22 is the word "dropped" (no route at core2) over a routing table
     the snapshot shows to be incomplete, so `bandOfTrace` is UNDETERMINED. The canvas used to band
     it by the outcome word and drew the red stop octagon under a label reading "? UNDECIDED". */
  const PARTIAL_RIB_DROP = { srcIp: "10.0.20.10", dstIp: "10.0.40.50", protocol: "tcp" as const, dstPort: 22, srcPort: null };

  it("the case is real: an undecided refusal exists in this snapshot", () => {
    const t = traceFlow(PARTIAL_RIB_DROP);
    expect(bandOfOutcome(t.outcome), `outcome word ${t.outcome}`).toBe("REFUTED");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
  });

  it("an undecided refusal ends in the ring, never in the alarm", () => {
    const m = terminalOf(PARTIAL_RIB_DROP);
    expect(m.stop).toBe(false);
    expect(m.undecided).toBe(true);
    expect(terminalOf(PARTIAL_RIB_DROP, true).alarmSegment).toBe(false);
  });

  it("a trace refused before any hop draws no terminal mark at all", () => {
    /* The flows the three-state tests used to call RESOLVED and REFUTED: both are sourced by core1's
       own address and are now refused as router-originated, so nothing is drawn — neither the alarm
       nor a green ending that would read as a decided result. */
    for (const flow of [
      { srcIp: "10.0.30.1", dstIp: "10.0.10.50", protocol: "tcp" as const, dstPort: 22, srcPort: null },
      { srcIp: "10.0.20.2", dstIp: "10.0.10.50", protocol: "tcp" as const, dstPort: 22, srcPort: null },
    ]) {
      expect(traceFlow(flow).hops).toEqual([]);
      const m = terminalOf(flow);
      expect(m.stop).toBe(false);
      expect(m.alarmSegment).toBe(false);
      expect(bandOfTrace(traceFlow(flow))).toBe("UNDETERMINED");
    }
  });
});

describe("a terminal glyph never occupies its chassis' space or screen area (C5 critic)", () => {
  const half = [8, 1.6, 6] as const;
  const anchor = { x: 40, y: 10, z: -20, top: 11.6, half };
  const chassisR = Math.hypot(...half);

  it("is disjoint from the chassis bounding sphere, across the line of sight, at every orbit", () => {
    const cam = new PerspectiveCamera(40, 1.6, 1, 2000);
    const out = new Vector3();
    const view = new Vector3();
    const offset = new Vector3();
    let checked = 0;
    for (const polarDeg of [5, 30, 55, 80, 89]) {
      for (const azDeg of [0, 45, 120, 200, 300]) {
        const p = (polarDeg * Math.PI) / 180;
        const a = (azDeg * Math.PI) / 180;
        cam.position.set(anchor.x + 200 * Math.sin(p) * Math.sin(a), anchor.y + 200 * Math.cos(p), anchor.z + 200 * Math.sin(p) * Math.cos(a));
        cam.lookAt(anchor.x, anchor.y, anchor.z);
        cam.updateMatrixWorld();
        for (const r of [STOP_GLYPH_RADIUS, UNDECIDED_GLYPH_RADIUS]) {
          placeTerminalGlyph(anchor, cam.quaternion, r, out);
          offset.set(out.x - anchor.x, out.y - anchor.y, out.z - anchor.z);
          // In space: the glyph's bounding sphere does not reach the chassis' (hence nor its AABB).
          expect(offset.length() - r - chassisR).toBeGreaterThanOrEqual(GLYPH_CLEARANCE - 1e-6);
          // On screen: the offset is perpendicular to the line of sight, so the separation is the
          // full offset, not a foreshortened part of it.
          cam.getWorldDirection(view);
          expect(Math.abs(offset.dot(view))).toBeLessThan(1e-6 * offset.length() + 1e-9);
          checked += 1;
        }
      }
    }
    expect(checked).toBe(50);
  });
});
