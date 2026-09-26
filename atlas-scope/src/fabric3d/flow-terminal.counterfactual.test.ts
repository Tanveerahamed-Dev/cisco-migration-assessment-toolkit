/**
 * flow-terminal.counterfactual.test.ts — the three terminal marks, each drawn for a REAL trace of its band.
 *
 * Moved out of flow-terminal.test.ts on 2026-09-22. That file exercised the RESOLVED and REFUTED marks
 * on flows sourced from core1's own SVI addresses (10.0.30.1, 10.0.20.2), which were the only decided
 * traces the snapshot produced — and they were decided only because the engine walked a packet the
 * router ORIGINATES as though it arrived inbound on that SVI (auditor, B2). The engine now refuses
 * such a source, and every remaining trace rests on a routing table the snapshot shows incomplete
 * (auditor, B1), so the shipped snapshot has no RESOLVED or REFUTED trace to draw at all.
 *
 * The overlay's three-state rule is still the thing under test, so this file runs the real engine
 * over the real compiled snapshot with two COMPLETENESS producers answered counterfactually: core1's
 * and core2's routing tables treated as complete, and every physical port a source could arrive by
 * treated as observed binding no list. Routes, ACL lines, bindings and FHRP records are unchanged.
 * Vitest isolates modules per file, so the counterfactual never reaches another test or the product.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("../forwarding/rib-completeness", async (orig) => {
  const actual = await orig<typeof import("../forwarding/rib-completeness")>();
  return { ...actual, ribIncompleteness: () => [], ribIncompletenessSentence: () => null };
});
vi.mock("../forwarding/bindings", async (orig) => {
  const actual = await orig<typeof import("../forwarding/bindings")>();
  return { ...actual, physicalIngressStates: () => [] };
});

import { bandOfTrace } from "../core/claims";
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

/* Host addresses in 10.0.30.0/24, whose one gateway is core1 Vlan30 (no FHRP alternate). */
const DELIVERED = { srcIp: "10.0.30.5", dstIp: "10.0.10.50", protocol: "tcp" as const, dstPort: 443, srcPort: null };
const DENIED = { srcIp: "10.0.30.5", dstIp: "10.0.40.5", protocol: "tcp" as const, dstPort: 443, srcPort: null };
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
  it("the counterfactual really does produce one of each outcome band", () => {
    // Guard the guard: if the producer stopped emitting an indeterminate outcome, every assertion
    // below would still pass while testing nothing.
    expect(bandOfTrace(traceFlow(DELIVERED))).toBe("RESOLVED");
    expect(bandOfTrace(traceFlow(DENIED))).toBe("REFUTED");
    expect(bandOfTrace(traceFlow(UNDECIDED))).toBe("UNDETERMINED");
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

describe("the terminal mark follows the TRACE band (C5 critic), over decided and undecided traces alike", () => {
  it("every mark the overlay draws agrees with bandOfTrace, over a sweep of real flows", () => {
    let refuted = 0;
    let undetermined = 0;
    let resolved = 0;
    for (const src of ["10.0.10.50", "10.0.20.10", "10.0.30.5", "10.0.40.50"]) {
      for (const dst of ["10.0.10.10", "10.0.10.50", "10.0.20.10", "10.0.30.10", "10.0.40.5", "10.0.40.50"]) {
        if (src === dst) continue;
        for (const dstPort of [22, 443, 3389]) {
          const flow = { srcIp: src, dstIp: dst, protocol: "tcp" as const, dstPort, srcPort: null };
          const trace = traceFlow(flow);
          // A trace with no hops draws nothing at all, so it has no terminal mark to check.
          if (trace.hops.length === 0) continue;
          const band = bandOfTrace(trace);
          const m = terminalOf(flow);
          expect(m.stop, `${src}->${dst}:${dstPort}`).toBe(band === "REFUTED");
          expect(m.undecided, `${src}->${dst}:${dstPort}`).toBe(band === "UNDETERMINED");
          if (band === "REFUTED") refuted += 1;
          else if (band === "UNDETERMINED") undetermined += 1;
          else resolved += 1;
        }
      }
    }
    // Every branch of the assertion above ran at least once on the real data.
    expect(undetermined).toBeGreaterThan(0);
    expect(refuted).toBeGreaterThan(0);
    expect(resolved).toBeGreaterThan(0);
  });
});
