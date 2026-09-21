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

import { bandOfOutcome } from "../core/claims";
import { traceFlow } from "../forwarding/engine";
import { createFlowOverlay, type TraceSegmentSource } from "./flow";
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

const DELIVERED = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp" as const, dstPort: 443, srcPort: null };
const DENIED = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp" as const, dstPort: 3389, srcPort: null };
const UNDECIDED = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "icmp" as const, dstPort: null, srcPort: null };

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
            { ...first, nextHost: "core2" },
            { ...first, index: 1, host: "core2", nextHost: null },
          ],
        }
      : real;
  const overlay = createFlowOverlay(readTokens("dark"));
  try {
    overlay.setTrace(trace, 0, segmentSource());
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

describe("the trace's terminal mark has three states, not two", () => {
  it("the snapshot really does produce one of each outcome band", () => {
    // Guard the guard: if the producer stopped emitting an indeterminate outcome, every assertion
    // below would still pass while testing nothing.
    expect(bandOfOutcome(traceFlow(DELIVERED).outcome)).toBe("RESOLVED");
    expect(bandOfOutcome(traceFlow(DENIED).outcome)).toBe("REFUTED");
    expect(bandOfOutcome(traceFlow(UNDECIDED).outcome)).toBe("UNDETERMINED");
  });

  it("a REFUTED trace ends in the alarm, and only a REFUTED one does", () => {
    const denied = terminalOf(DENIED);
    expect(denied.stop, "a denied flow keeps the octagonal alarm").toBe(true);
    expect(denied.undecided).toBe(false);
    // Over a drawn path, it also keeps the 6 px critical terminal segment.
    expect(terminalOf(DENIED, true).alarmSegment).toBe(true);
  });

  it("an UNDETERMINED trace ends in the ring, never in the alarm", () => {
    const undecided = terminalOf(UNDECIDED);
    expect(undecided.undecided, "the open ring marks where deciding stopped").toBe(true);
    expect(
      undecided.stop,
      "the engine declined to decide this flow; the canvas may not assert that it was stopped",
    ).toBe(false);
    expect(
      terminalOf(UNDECIDED, true).alarmSegment,
      "and it may not paint the critical terminal segment either, even over a drawn path",
    ).toBe(false);
  });

  it("a RESOLVED trace ends in neither", () => {
    const delivered = terminalOf(DELIVERED);
    expect(delivered.stop).toBe(false);
    expect(delivered.undecided).toBe(false);
    expect(delivered.alarmSegment).toBe(false);
  });

  it("the denied and the undecided endings are not the same picture", () => {
    /* The assertion the predecessor of this file could not make: the two states differ in the
       objects drawn, not only in a colour or a word somewhere else on the page. */
    const denied = terminalOf(DENIED);
    const undecided = terminalOf(UNDECIDED);
    expect([denied.stop, denied.undecided, denied.alarmSegment]).not.toEqual([
      undecided.stop,
      undecided.undecided,
      undecided.alarmSegment,
    ]);
  });

  it("clearing the trace clears both terminal marks", () => {
    const overlay = createFlowOverlay(readTokens("dark"));
    try {
      overlay.setTrace(traceFlow(UNDECIDED), 0, segmentSource());
      expect(overlay.emissiveObjects().find((o) => o.name === "trace-undecided")?.visible).toBe(true);
      overlay.setTrace(null, null, segmentSource());
      expect(overlay.emissiveObjects().find((o) => o.name === "trace-undecided")?.visible).toBe(false);
      expect(overlay.emissiveObjects().find((o) => o.name === "trace-stop")?.visible).toBe(false);
    } finally {
      overlay.dispose();
    }
  });
});
