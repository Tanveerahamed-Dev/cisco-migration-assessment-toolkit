/**
 * engine.work-bound.test.ts — the engine's cost, bounded STRUCTURALLY rather than by a clock.
 *
 * WHY (acceptance F2 / O26). `engine.test.ts` used to gate the trace and the counterexample search
 * on a median-of-7 wall-clock figure under a 50 ms tripwire. Under multi-agent load that median was
 * measured at 54.66 ms for a search that takes ~2–5 ms on a quiet host: a red from it could not be
 * told apart from a regression, so it was no gate. Time budgets belong to the E harnesses, which
 * measure the running application and label themselves laboratory.
 *
 * What a unit test CAN assert, identically on a quiet host and a loaded one, is how much work the
 * engine does, in its own units (`engineWork()`): `traceFlow` calls, hop-loop iterations and ACL
 * line matches. Each bound below is derived from the data and the engine's declared structure —
 *
 *   traces per trace request      ≤ max(1, ingressCandidates(src).length)
 *                                   (the trace, plus one memoised trace per alternate ingress,
 *                                    which cannot itself recurse)
 *   traces per counterexample     ≤ candidates traced × max(1, ingressCandidates(src).length),
 *                                   candidates traced ≤ COUNTEREXAMPLE_CANDIDATE_CAP
 *   hop iterations                ≤ traces × TTL_LIMIT
 *   ACL line matches              ≤ hop iterations × ACL_PASSES_PER_HOP × (most ACL lines on any host)
 *
 * — so a search that stops honouring its candidate cap, a trace that re-traces itself, or an ACL
 * pass nested inside another turns this red on any machine. Timing is still measured, and REPORTED
 * as a test annotation; it is never asserted.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import type { AclLine, Flow } from "../core/types";
import { FLOW_PROTOCOLS, formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4, protocolCarriesPorts } from "./ip";
import {
  ACL_PASSES_PER_HOP,
  COUNTEREXAMPLE_CANDIDATE_CAP,
  counterexample,
  engineWork,
  evaluateAcls,
  ingressCandidates,
  suggestedFlows,
  traceFlow,
  TTL_LIMIT,
  type EngineWork,
} from "./engine";

/** The most ACL lines any one host carries, read from the snapshot. */
const MAX_LINES_ON_A_HOST = Math.max(
  0,
  ...Object.values(fabric.acls).map((named) => Object.values(named).reduce((n, lines) => n + lines.length, 0)),
);

const delta = (a: EngineWork, b: EngineWork): EngineWork => ({
  traces: b.traces - a.traces,
  hops: b.hops - a.hops,
  lineMatches: b.lineMatches - a.lineMatches,
});

/** How many traces one request from this source may run: itself plus each alternate ingress. */
const tracesPerRequest = (srcIp: string): number => {
  const src = parseIpv4(srcIp);
  return Math.max(1, src === null ? 0 : ingressCandidates(src).length);
};

/** The two bounds that follow from a trace count, whatever issued the traces. */
function expectInnerBounds(w: EngineWork, where: string): void {
  expect(w.hops, `${where}: hop iterations vs ${w.traces} traces × TTL ${TTL_LIMIT}`).toBeLessThanOrEqual(w.traces * TTL_LIMIT);
  expect(w.lineMatches, `${where}: line matches vs ${w.hops} hops × ${ACL_PASSES_PER_HOP} passes × ${MAX_LINES_ON_A_HOST} lines`).toBeLessThanOrEqual(
    w.hops * ACL_PASSES_PER_HOP * MAX_LINES_ON_A_HOST,
  );
}

/** The candidate count a not-found counterexample reports it traced ("None of the N nearby variations"). */
function reportedCandidates(reason: string): number | null {
  const m = /None of the (\d+) nearby variations/.exec(reason);
  return m === null ? null : Number(m[1]);
}

/** Suggested flows plus flows between hosts in every observed subnet, over every protocol the engine accepts. */
function sweepFlows(): Flow[] {
  const addrs = new Set<string>(["198.51.100.7", "8.8.8.8"]);
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    const h = a === null ? null : hostAddressIn(a.prefix, 10);
    if (h !== null) addrs.add(formatIpv4(h));
  }
  const flows: Flow[] = suggestedFlows().map((s) => s.flow);
  const list = [...addrs].sort();
  for (const srcIp of list)
    for (const dstIp of list) {
      if (srcIp === dstIp) continue;
      for (const protocol of FLOW_PROTOCOLS)
        for (const dstPort of protocolCarriesPorts(protocol) ? [22, 443, 3389] : [null]) flows.push({ srcIp, dstIp, protocol, dstPort, srcPort: null });
    }
  return flows;
}

describe("the engine's work is bounded by the data, not by the machine (F2 / O26)", () => {
  const flows = sweepFlows();

  it("a precondition: the snapshot has ACL lines, so the line-match bound is not vacuous", () => {
    expect(MAX_LINES_ON_A_HOST).toBeGreaterThan(0);
  });

  it("every trace does at most one trace per candidate ingress, and the hop and ACL work that follows from it", async ({ annotate }) => {
    let maxMs = 0;
    let sawAlternate = false;
    let sawLines = false;
    for (const f of flows) {
      const before = engineWork();
      const t = traceFlow(f);
      const w = delta(before, engineWork());
      const where = JSON.stringify(f);
      expect(w.traces, `${where}: traces`).toBeGreaterThanOrEqual(1);
      expect(w.traces, `${where}: traces vs ${tracesPerRequest(f.srcIp)} ingress candidates`).toBeLessThanOrEqual(tracesPerRequest(f.srcIp));
      expectInnerBounds(w, where);
      if (w.traces > 1) sawAlternate = true;
      if (w.lineMatches > 0) sawLines = true;
      maxMs = Math.max(maxMs, t.elapsedMs);
      /* The TIGHT form. Alternate-ingress traces are memoised per flow, so the same request made
         again is exactly one trace. A trace that re-traced itself, or anything else, would show here
         even for a source with several ingress candidates, where the bound above has slack. */
      const again = engineWork();
      traceFlow(f);
      const w2 = delta(again, engineWork());
      expect(w2.traces, `${where}: the same trace, memo warm`).toBe(1);
      expectInnerBounds(w2, `${where} (warm)`);
    }
    // Non-vacuity: the sweep reaches the alternate-ingress re-trace and the ACL matcher.
    expect(sawAlternate).toBe(true);
    expect(sawLines).toBe(true);
    await annotate(`${flows.length} traces; slowest single trace ${maxMs.toFixed(2)} ms (reported, not asserted)`);
  });

  it("every counterexample search traces at most its capped candidates, each at most once per ingress", async ({ annotate }) => {
    let searched = 0;
    let found = 0;
    let maxMs = 0;
    for (const f of flows) {
      const t = traceFlow(f);
      if (t.outcome !== "denied" && t.outcome !== "dropped") continue;
      const before = engineWork();
      const started = performance.now();
      const cx = counterexample(f, t);
      maxMs = Math.max(maxMs, performance.now() - started);
      const w = delta(before, engineWork());
      const where = JSON.stringify(f);
      const traced = cx.found ? COUNTEREXAMPLE_CANDIDATE_CAP : reportedCandidates(cx.reason);
      if (!cx.found && /blocking hop/.test(cx.reason)) {
        expect(w.traces, `${where}: nothing to vary, nothing traced`).toBe(0);
        continue;
      }
      expect(traced, `${where}: ${cx.found ? "" : cx.reason}`).not.toBeNull();
      expect(traced!, where).toBeLessThanOrEqual(COUNTEREXAMPLE_CANDIDATE_CAP);
      expect(w.traces, `${where}: traces vs ${traced} candidates × ${tracesPerRequest(f.srcIp)} ingresses`).toBeLessThanOrEqual(traced! * tracesPerRequest(f.srcIp));
      expectInnerBounds(w, where);
      /* Tight form, as above: made again, every alternate is memoised, so the search costs exactly
         one trace per candidate it tries — never more than the candidates it reports. */
      if (!cx.found) {
        const again = engineWork();
        counterexample(f, t);
        const w2 = delta(again, engineWork());
        expect(w2.traces, `${where}: the same search, memo warm, vs ${traced} candidates`).toBeLessThanOrEqual(traced!);
        expectInnerBounds(w2, `${where} (warm)`);
      }
      searched += 1;
      if (cx.found) found += 1;
    }
    expect(searched, "denied or dropped flows whose search ran").toBeGreaterThan(10);
    await annotate(`${searched} searches (${found} found); slowest ${maxMs.toFixed(2)} ms (reported, not asserted)`);
  });

  it("the headline flow's search traces no more candidates than it says it considered", () => {
    const f: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null };
    const t = traceFlow(f);
    const before = engineWork();
    const cx = counterexample(f, t);
    const w = delta(before, engineWork());
    expect(cx.found).toBe(false);
    const n = cx.found ? null : reportedCandidates(cx.reason);
    expect(n).not.toBeNull();
    expect(n!).toBeGreaterThan(0);
    expect(w.traces).toBeLessThanOrEqual(n! * tracesPerRequest(f.srcIp));
    // Made again (every alternate memoised): every candidate but one identical to the flow itself is
    // traced exactly once — and nothing more.
    const again = engineWork();
    counterexample(f, t);
    const w2 = delta(again, engineWork());
    expect(w2.traces).toBeGreaterThanOrEqual(n! - 1);
    expect(w2.traces).toBeLessThanOrEqual(n!);
  });

  it("one ACL evaluation asks the matcher about each line at most ACL_PASSES_PER_HOP times, however long the lists", () => {
    /* The snapshot's lists are short (the longest holds a handful of lines), and on a list of n
       lines a quadratic costs n², which a 5-pass linear bound cannot tell from 5n until n > 5. So the
       real lines are also handed to the engine as LONGER lists through the `named` seam — every
       collected line of the host in one list, and that list twice over under two names. No line is
       invented; the lists are only made long enough for a nested pass to show. A list stops at the
       first line that decides, and every collected list ends in `deny ip any any`, so a concatenation
       would stop at the first list's end; the long shapes therefore leave out the lines that match
       every packet (ip, any, any), so a flow none of the rest matches walks the whole list. */
    const matchesEveryPacket = (l: AclLine): boolean =>
      (l.proto ?? "").toLowerCase() === "ip" && [l.src, l.dst].every((a) => a !== null && a.group === null && a.wild === "255.255.255.255");
    const f0 = flows.length;
    let evaluated = 0;
    for (const [host, named] of Object.entries(fabric.acls)) {
      const every = Object.keys(named)
        .sort()
        .flatMap((n) => named[n] ?? [])
        .filter((l) => !matchesEveryPacket(l));
      if (every.length === 0) continue;
      const shapes: Record<string, AclLine[]>[] = [named, { ALL: every }, { ALL_A: every, ALL_B: [...every, ...every] }];
      for (const shape of shapes) {
        const total = Object.values(shape).reduce((n, ls) => n + ls.length, 0);
        for (const f of flows) {
          const src = parseIpv4(f.srcIp);
          const dst = parseIpv4(f.dstIp);
          if (src === null || dst === null) continue;
          const before = engineWork();
          evaluateAcls(host, f, src, dst, shape);
          const w = delta(before, engineWork());
          expect(w.lineMatches, `${host} ${Object.keys(shape).join("+")} (${total} lines) ${JSON.stringify(f)}`).toBeLessThanOrEqual(ACL_PASSES_PER_HOP * total);
          evaluated += 1;
        }
      }
    }
    expect(evaluated).toBeGreaterThanOrEqual(f0);
  });
});
