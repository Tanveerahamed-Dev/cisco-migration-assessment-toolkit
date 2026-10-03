/**
 * engine.ingress-decider.test.ts — an alternate ingress reproduces a result only when the same element
 * decided it (acceptance A3; 2026-10 refuter overturn).
 *
 * The alternate-ingress check (`ingressPolicyGaps`) counted an alternate FHRP member as reproducing a trace
 * whenever its own trace ended with the same OUTCOME word and nothing on its path left open. The verdict a
 * reader quotes is not the word, it is the deciding line: tcp 10.0.20.50 -> 10.0.30.10:22 enters at the HSRP
 * Active core2 and is denied at core1 by PROTECT_SERVERS line 4 of 4, but entered at the Standby core1 it is
 * denied first by core1's inbound VOICE_FILTER on Vlan20, line 3 of 3. The caveat nevertheless said the
 * result "does not rest on that choice" while naming the PROTECT_SERVERS line as the blocker.
 *
 * The deciding element is read here from each trace's own hops, independently of the engine's comparison:
 * a refusal by its blocking host and cite (`blockingHop`), a delivery by the host it is delivered at, any
 * other outcome by its last hop and that hop's deciding cite.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import type { Flow, Trace } from "../core/types";
import { blockingHop, ingressCandidates, suggestedFlows, traceFlow, traceViaIngress, unobservedPolicyInputs } from "./engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4 } from "./ip";
import { describeGolden } from "../test-support/golden-sample";
import { GOLDEN_FORWARDING } from "../test-support/golden-expectations";
import { lazy, literal, needSome } from "../test-support/test-subjects";

const NOT_RESTING = "does not rest on that choice";

/** What decided a trace, stated from its own hops. */
function decider(t: Trace): string {
  const last = t.hops[t.hops.length - 1];
  if (t.outcome === "delivered") return `delivered at ${last?.host ?? "(no hop)"}`;
  const b = blockingHop(t);
  if (b !== null) return `${t.outcome} at ${b.hop.host} by ${b.evidence.cite}`;
  return `${t.outcome} at ${last?.host ?? "(no hop)"} by ${last?.decidedBy?.cite ?? "(nothing recorded)"}`;
}

/** The ingress-choice caveat a trace carries, if its first hop was chosen among FHRP / shared-subnet members. */
const ingressCaveat = (t: Trace): string | undefined => t.caveats.find((c) => c.includes("was taken as ingress"));

/** Every suggested flow, plus one source in every SVI subnet to one destination in every other, on three ports. */
function flows(): Flow[] {
  const srcs = new Set<string>(suggestedFlows().map((s) => s.flow.srcIp));
  const dsts = new Set<string>(suggestedFlows().map((s) => s.flow.dstIp));
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    const h = a === null ? null : hostAddressIn(a.prefix, 50);
    const d = a === null ? null : hostAddressIn(a.prefix, 10);
    if (h !== null) srcs.add(formatIpv4(h));
    if (d !== null) dsts.add(formatIpv4(d));
  }
  const out: Flow[] = suggestedFlows().map((s) => s.flow);
  for (const s of srcs) for (const d of dsts) for (const p of [22, 443, 3389]) if (s !== d) out.push({ srcIp: s, dstIp: d, protocol: "tcp", dstPort: p, srcPort: null });
  return out;
}

describe("A3: an alternate ingress reproduces a result only when the same element decided it", () => {
  const traces = lazy(() => flows().map(traceFlow));

  it("'does not rest on that choice' and 'traced with X as its ingress' appear only when X's trace is decided by the identical element", (ctx) => {
    let compared = 0;
    let same = 0;
    let differs = 0;
    for (const t of traces()) {
      const src = parseIpv4(t.flow.srcIp);
      const first = t.hops[0];
      if (src === null || first === undefined) continue;
      const cands = ingressCandidates(src);
      if (!cands.some((c) => c.host === first.host)) continue;
      const caveat = ingressCaveat(t) ?? "";
      const gapHosts = new Set(unobservedPolicyInputs(t).filter((g) => g.kind === "ingress-alternate").map((g) => g.host));
      for (const alt of cands) {
        if (alt.host === first.host) continue;
        const at = traceViaIngress(t.flow, alt.host);
        if (at.hops[0]?.host !== alt.host) continue;
        compared += 1;
        const where = `${JSON.stringify(t.flow)} via ${alt.host}: chosen "${decider(t)}", alternate "${decider(at)}" :: ${caveat}`;
        const tracedWith = new RegExp(`traced with [^.;]*\\b${alt.host}\\b[^.;]* as its ingress`).test(caveat);
        if (decider(at) === decider(t)) {
          same += 1;
          continue;
        }
        differs += 1;
        expect(tracedWith, `${where}: an alternate decided by another element was called a reproduction`).toBe(false);
        expect(caveat.includes(NOT_RESTING), `${where}: the result rests on the ingress choice`).toBe(false);
        expect(gapHosts.has(alt.host), `${where}: no ingress-alternate gap names ${alt.host}`).toBe(true);
      }
      /* The sentence as a whole: it may only appear when every alternate traced from was decided identically. */
      if (caveat.includes(NOT_RESTING)) {
        for (const alt of cands) {
          if (alt.host === first.host) continue;
          const at = traceViaIngress(t.flow, alt.host);
          if (at.hops[0]?.host !== alt.host) continue;
          expect(decider(at), `${JSON.stringify(t.flow)} :: ${caveat}`).toBe(decider(t));
        }
      }
    }
    needSome(ctx, compared, "flow traced from an alternate ingress");
    needSome(ctx, same, "alternate ingress decided by the identical element");
    needSome(ctx, differs, "alternate ingress decided by a different element");
  });

  it("a different deciding element is named in the trace: both cites, and that the deciding line depends on the ingress", (ctx) => {
    let named = 0;
    for (const t of traces()) {
      for (const g of unobservedPolicyInputs(t).filter((x) => x.kind === "ingress-alternate")) {
        const at = traceViaIngress(t.flow, g.host);
        if (at.hops[0]?.host !== g.host || at.outcome !== t.outcome || decider(at) === decider(t)) continue;
        expect(g.label, JSON.stringify(t.flow)).toMatch(/depends on the ingress/);
        /* Both elements are named: a delivery by its delivering host, anything else by its deciding record. */
        const element = (x: Trace): string =>
          x.outcome === "delivered"
            ? `delivered at ${x.hops[x.hops.length - 1]?.host ?? ""}`
            : (blockingHop(x)?.evidence.cite ?? x.hops[x.hops.length - 1]?.decidedBy?.cite ?? "");
        expect(g.label, JSON.stringify(t.flow)).toMatch(literal(element(t)));
        expect(g.label, JSON.stringify(t.flow)).toMatch(literal(element(at)));
        named += 1;
      }
    }
    needSome(ctx, named, "same-outcome alternate ingress decided by a different element");
  });
});

describeGolden("A3: the refuter's flow — denied either way, by a different line at each ingress", () => {
  const g = GOLDEN_FORWARDING.ingressDependentDenial;

  it("the alternate is traced and decided by the other line", () => {
    const t = traceFlow(g.flow);
    expect(t.hops[0]?.host).toBe(g.chosen);
    expect(t.outcome).toBe("denied");
    expect(blockingHop(t)?.hop.host).toBe(g.blockingHost);
    expect(blockingHop(t)?.evidence.cite).toBe(g.chosenCite);
    const at = traceViaIngress(g.flow, g.alternate);
    expect(at.hops[0]?.host).toBe(g.alternate);
    expect(at.outcome).toBe("denied");
    expect(blockingHop(at)?.hop.host).toBe(g.blockingHost);
    expect(blockingHop(at)?.evidence.cite).toBe(g.alternateCite);
  });

  it("the caveat no longer says the result does not rest on the ingress choice, and the trace names both lines", () => {
    const t = traceFlow(g.flow);
    const caveat = ingressCaveat(t) ?? "";
    expect(caveat).not.toContain(NOT_RESTING);
    expect(caveat).toMatch(new RegExp(`may (instead )?enter via [^.;]*\\b${g.alternate}\\b`));
    const gap = unobservedPolicyInputs(t).find((x) => x.kind === "ingress-alternate" && x.host === g.alternate);
    expect(gap?.label).toMatch(/depends on the ingress/);
    expect(gap?.label).toMatch(literal(g.chosenCite));
    expect(gap?.label).toMatch(literal(g.alternateCite));
    /* An ingress-alternate gap undecides a refusal, and the claim names it (claim-honesty rule). */
    expect(t.claim).toMatch(/That denial is not decided/);
    expect(t.claim).toMatch(literal(g.alternateCite));
  });
});
