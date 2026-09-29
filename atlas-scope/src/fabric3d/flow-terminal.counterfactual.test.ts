/**
 * flow-terminal.counterfactual.test.ts — the three terminal marks, each drawn for a REAL trace of its band.
 *
 * Moved out of flow-terminal.test.ts on 2026-09-22. That file exercised the RESOLVED and REFUTED marks
 * on flows sourced from core1's own SVI addresses (10.0.30.1, 10.0.20.2), which were the only decided
 * traces the snapshot produced — and they were decided only because the engine walked a packet the
 * router ORIGINATES as though it arrived inbound on that SVI (auditor, B2). The engine now refuses
 * such a source, and every remaining trace rests on a routing table the snapshot shows incomplete
 * (auditor, B1), so the then-shipped snapshot had no RESOLVED or REFUTED trace to draw at all.
 *
 * UPDATED phase 3: the regenerated sample does hold decided two-hop traces (dist1 -> core1), so the
 * subjects below are resolved by PROPERTY from a sweep over the loaded fabric — the first trace of each
 * band, a two-hop one first — and a real multi-hop trace draws its own path. The counterfactual stays: it
 * widens the set of decided traces on any snapshot whose tables or ports are partly unobserved.
 *
 * The overlay's three-state rule is still the thing under test, so this file runs the real engine
 * over the real compiled snapshot with two COMPLETENESS producers answered counterfactually: core1's
 * and core2's routing tables treated as complete, and every physical port a source could arrive by
 * treated as observed binding no list. Routes, ACL lines, bindings and FHRP records are unchanged.
 * Vitest isolates modules per file, so the counterfactual never reaches another test or the product.
 */
import { describe, expect, it, vi, type TestContext } from "vitest";

vi.mock("../forwarding/rib-completeness", async (orig) => {
  const actual = await orig<typeof import("../forwarding/rib-completeness")>();
  return { ...actual, ribIncompleteness: () => [], ribIncompletenessSentence: () => null };
});
vi.mock("../forwarding/bindings", async (orig) => {
  const actual = await orig<typeof import("../forwarding/bindings")>();
  return { ...actual, physicalIngressStates: () => [] };
});

import { bandOfTrace } from "../core/claims";
import { fabric } from "../core/data";
import { traceFlow } from "../forwarding/engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "../forwarding/ip";
import { lazy, need } from "../forwarding/test-subjects";
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

/* UPDATED phase 3: the three subjects were typed flows on the old sample (10.0.30.5 -> 10.0.40.5 was the
   denied one; on the regenerated sample 10.0.40.0/24 is routed to dist1 and that flow is delivered). They
   are now resolved by PROPERTY from a sweep over the loaded fabric — the first trace of each band, a
   two-hop one first where the data has it (so the drawn path is real, not derived) — so the three-state
   rule is tested on whatever snapshot is loaded. */
type Probe = { srcIp: string; dstIp: string; protocol: "tcp" | "icmp"; dstPort: number | null; srcPort: null };
function sweep(): Probe[] {
  const addrs = new Set<string>();
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    for (const off of [5, 10, 50]) {
      const h = a === null ? null : hostAddressIn(a.prefix, off);
      if (h !== null) addrs.add(formatIpv4(h));
    }
  }
  for (const e of fabric.endpoints) if (e.ip !== null) addrs.add(e.ip);
  const out: Probe[] = [];
  for (const s of [...addrs].sort())
    for (const d of [...addrs].sort()) {
      if (s === d) continue;
      for (const p of [22, 443, 3389]) out.push({ srcIp: s, dstIp: d, protocol: "tcp", dstPort: p, srcPort: null });
      out.push({ srcIp: s, dstIp: d, protocol: "icmp", dstPort: null, srcPort: null });
    }
  return out;
}
/* Traced ONCE, on first use inside a test — never at module scope, where one fabric lacking a band threw at
   collection and took every test in the file with it (2026-09-28 verifier, D2: the golden-snapshot leg). */
const traced = lazy(() => sweep().map((f) => ({ f, t: traceFlow(f) })));
type Band = "RESOLVED" | "REFUTED" | "UNDETERMINED";
const BAND_NAME: Record<Band, string> = {
  RESOLVED: "RESOLVED trace under the counterfactual",
  REFUTED: "REFUTED trace under the counterfactual",
  UNDETERMINED: "UNDETERMINED trace under the counterfactual",
};
/** The first trace of the band (a two-hop one first), or a named not-applicable skip on a fabric without one. */
function subjectOf(ctx: TestContext, band: Band): Probe {
  const of = traced().filter(({ t }) => t.hops.length > 0 && bandOfTrace(t) === band);
  return need(ctx, (of.find(({ t }) => t.hops.length >= 2) ?? of[0])?.f, BAND_NAME[band]);
}


/**
 * Which terminal marks are drawn for a real trace of this flow.
 *
 * `twoHop` derives a second hop FROM the producer's own hop when asked AND the real trace is one hop
 * long: a one-hop trace draws no polyline at all, so the 6 px terminal SEGMENT (which needs a drawn path)
 * is unreachable on it. A real multi-hop trace is drawn as it is. Only the
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
    /* Derived only for a ONE-hop trace: a real multi-hop trace (phase 3) already draws its own path. */
    twoHop && first !== undefined && real.hops.length === 1
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
  it("the counterfactual really does produce one of each outcome band", (ctx) => {
    // Guard the guard: if the producer stopped emitting an indeterminate outcome, every assertion
    // below would still pass while testing nothing. On the reference sample all three are required.
    expect(bandOfTrace(traceFlow(subjectOf(ctx, "RESOLVED")))).toBe("RESOLVED");
    expect(bandOfTrace(traceFlow(subjectOf(ctx, "REFUTED")))).toBe("REFUTED");
    expect(bandOfTrace(traceFlow(subjectOf(ctx, "UNDETERMINED")))).toBe("UNDETERMINED");
  });

  it("a REFUTED trace ends in the alarm, and only a REFUTED one does", (ctx) => {
    const DENIED = subjectOf(ctx, "REFUTED");
    const denied = terminalOf(DENIED);
    expect(denied.stop, "a denied flow keeps the octagonal alarm").toBe(true);
    expect(denied.undecided).toBe(false);
    // Over a drawn path, it also keeps the 6 px critical terminal segment.
    expect(terminalOf(DENIED, true).alarmSegment).toBe(true);
  });

  it("an UNDETERMINED trace ends in the ring, never in the alarm", (ctx) => {
    const UNDECIDED = subjectOf(ctx, "UNDETERMINED");
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

  it("a RESOLVED trace ends in neither", (ctx) => {
    const delivered = terminalOf(subjectOf(ctx, "RESOLVED"));
    expect(delivered.stop).toBe(false);
    expect(delivered.undecided).toBe(false);
    expect(delivered.alarmSegment).toBe(false);
  });

  it("the denied and the undecided endings are not the same picture", (ctx) => {
    /* The assertion the predecessor of this file could not make: the two states differ in the
       objects drawn, not only in a colour or a word somewhere else on the page. */
    const denied = terminalOf(subjectOf(ctx, "REFUTED"));
    const undecided = terminalOf(subjectOf(ctx, "UNDETERMINED"));
    expect([denied.stop, denied.undecided, denied.alarmSegment]).not.toEqual([
      undecided.stop,
      undecided.undecided,
      undecided.alarmSegment,
    ]);
  });

  it("clearing the trace clears both terminal marks", (ctx) => {
    const UNDECIDED = subjectOf(ctx, "UNDETERMINED");
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
  it("every mark the overlay draws agrees with bandOfTrace, over a sweep of real flows", (ctx) => {
    let refuted = 0;
    let undetermined = 0;
    let resolved = 0;
    /* UPDATED phase 3: over the derived sweep (host addresses in every observed subnet) instead of a typed
       address list, so the rule is checked on whatever snapshot is loaded. Each flow is traced once (shared
       with the subjects above) and drawn on ONE overlay re-used across the sweep, so the cost is the drawing,
       not a scene built and disposed per flow — the whole sweep ran past the 30 s budget on the rename leg. */
    const overlay = createFlowOverlay(readTokens("dark"));
    try {
      for (const { f: flow, t: trace } of traced().filter(({ f }) => f.protocol === "tcp")) {
        // A trace with no hops draws nothing at all, so it has no terminal mark to check.
        if (trace.hops.length === 0) continue;
        const band = bandOfTrace(trace);
        overlay.setTrace(trace, 0, segmentSource());
        const by = (name: string) => overlay.emissiveObjects().find((o) => o.name === name);
        const where = `${flow.srcIp}->${flow.dstIp}:${flow.dstPort}`;
        expect(by("trace-stop")?.visible === true, where).toBe(band === "REFUTED");
        expect(by("trace-undecided")?.visible === true, where).toBe(band === "UNDETERMINED");
        overlay.setTrace(null, null, segmentSource());
        if (band === "REFUTED") refuted += 1;
        else if (band === "UNDETERMINED") undetermined += 1;
        else resolved += 1;
      }
    } finally {
      overlay.dispose();
    }
    // Every branch of the assertion above ran at least once — required on the reference sample; on another
    // fabric a band it cannot produce is named as not applicable.
    need(ctx, undetermined > 0 ? undetermined : undefined, BAND_NAME.UNDETERMINED);
    need(ctx, refuted > 0 ? refuted : undefined, BAND_NAME.REFUTED);
    need(ctx, resolved > 0 ? resolved : undefined, BAND_NAME.RESOLVED);
  });
});
