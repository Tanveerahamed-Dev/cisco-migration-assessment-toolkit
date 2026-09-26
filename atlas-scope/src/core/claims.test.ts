/**
 * Tests for the claim-honesty layer, run against the REAL compiled snapshot and the REAL forwarding
 * engine. Nothing here is fixture-shaped: every expectation was produced by running `traceFlow` on
 * the actual data and reading what came back, so a test passing here means the product's claims are
 * honest about THIS evidence, not about a convenient stand-in for it.
 */
import { describe, expect, it } from "vitest";
import {
  FORBIDDEN_CLAIM_WORDS,
  T1_verdict,
  T10_SAMPLE_PATH,
  T2_blockingHop,
  T3_outOfScope,
  T4_unmodelledHost,
  T8_coverageLine,
  absence,
  bandOfHop,
  bandOfOutcome,
  bandOfTrace,
  hopsSupportOutcome,
  claimBadge,
  forbiddenWordsIn,
  isAbsence,
  resolveAbsence,
  scopeTuple,
  sharePayload,
} from "./claims";
import { fabric } from "./data";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import type { Flow, Trace } from "./types";

const DENIED: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null };
// UPDATED: 10.0.10.50 -> 10.0.30.10:443 no longer traces delivered (it steps over an undecidable line in
// INET_RETURN), so the delivered case is a flow core2 delivers with nothing on its path undecided.
const DELIVERED: Flow = { srcIp: "10.0.20.10", dstIp: "10.0.10.10", protocol: "tcp", dstPort: 443, srcPort: null };
const NO_RIB: Flow = { srcIp: "10.0.40.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null };
const OFF_MODEL: Flow = { srcIp: "198.51.100.7", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null };

describe("badge strength is bounded by what the evidence supports", () => {
  it("never awards SCOPED to a trace that touched a host with no RIB", () => {
    const t = traceFlow(NO_RIB);
    expect(t.unmodelledHosts).toContain("dist1");
    expect(claimBadge(t)).toBe("INDETERMINATE");
  });

  it("marks a flow we cannot even enter as OUT OF SCOPE, not as a failure", () => {
    const t = traceFlow(OFF_MODEL);
    expect(t.outcome).toBe("out-of-scope");
    expect(claimBadge(t)).toBe("OUT OF SCOPE");
    expect(bandOfOutcome(t.outcome)).toBe("UNDETERMINED");
  });

  it("bands indeterminate as UNDETERMINED — never folded into success or failure", () => {
    expect(bandOfOutcome("indeterminate")).toBe("UNDETERMINED");
    expect(bandOfOutcome("out-of-scope")).toBe("UNDETERMINED");
    expect(bandOfOutcome("delivered")).toBe("RESOLVED");
    expect(bandOfOutcome("denied")).toBe("REFUTED");
    expect(bandOfOutcome("dropped")).toBe("REFUTED");
  });

  it("SCOPED is the ceiling: no badge in this product asserts proof", () => {
    const badges = suggestedFlows().map((s) => claimBadge(traceFlow(s.flow)));
    for (const b of badges) expect(["SCOPED", "PARTIAL", "INDETERMINATE", "OUT OF SCOPE", "INVALID INPUT"]).toContain(b);
  });
});

describe("the verdict header states its own denominators", () => {
  it("names the real RIB coverage, read from the data and not hardcoded", () => {
    const line = T1_verdict(traceFlow(DENIED));
    expect(line).toContain(`${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length} hosts in this topology have one`);
    // Guard against a future edit that inlines today's numbers as literals.
    expect(fabric.coverage.hostsWithRoutes).toBeLessThan(fabric.devices.length);
  });

  it("reports unmodelled hosts on the path rather than omitting them", () => {
    const t = traceFlow(NO_RIB);
    const s = scopeTuple(t);
    expect(s.unmodelledOnPath).toBeGreaterThan(0);
    expect(T1_verdict(t)).toContain("could not be modelled");
    /* 2026-09-22 auditor (B2): the one hop was a host with NO RIB, so the sentence must not read as
       if it were on one, and a filtering question left open must not be said to have been "answered". */
    const onRib = t.hops.filter((h) => fabric.coverage.routableHosts.includes(h.host)).length;
    expect(T1_verdict(t)).toContain(`${onRib} of them on a host with a collected RIB`);
    expect(T1_verdict(t)).not.toContain("answered without");
    if (s.policyGaps.some((g) => g.kind !== "rib-partial")) expect(T1_verdict(t)).toContain("left open for want of collected evidence");
  });

  it("prints no counts for an out-of-scope result: no path was evaluated", () => {
    /* REGRESSION: "traversed 0 hops …; 0 hosts on this path could not be modelled; 0 evidence items
       were indeterminate" for a search that never ran rendered an absence as a clean count. */
    const t = traceFlow({ srcIp: "198.51.100.7", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null });
    expect(t.outcome).toBe("out-of-scope");
    const line = T1_verdict(t);
    expect(line).toContain("no path was evaluated");
    expect(line).not.toMatch(/\b0 (hops?|hosts? on this path|evidence items?)\b/);
    expect(line).toContain(`${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length}`);
  });

  it("uses singular and plural correctly, because '1 hops' reads as a bug in the data", () => {
    const one = T1_verdict(traceFlow(DELIVERED));
    expect(one).toContain("traversed 1 hop, ");
    expect(one).not.toContain("1 hops");
    /* The hop count and the fleet denominator are separate clauses (2026-09-22 auditor, B2): how many
       traversed hops were on a RIB host is stated on its own, never fused with "N of M hosts". */
    expect(one).not.toMatch(/hops? across \d+ of \d+ hosts/);
    expect(one).toMatch(/\b1 of them on a host with a collected RIB/);
  });
});

describe("the blocking-hop answer names the literal configuration line", () => {
  it("gives host, ACL name and the raw config text with a citation", () => {
    const t = traceFlow(DENIED);
    expect(t.outcome).toBe("denied");
    const hop = t.hops.find((h) => h.verdict === "denied");
    expect(hop).toBeDefined();
    const sentence = T2_blockingHop(hop!);
    expect(sentence).not.toBeNull();
    expect(sentence!).toContain("core1");
    expect(sentence!).toContain("PROTECT_SERVERS");
    expect(sentence!).toContain("deny ip any any");
    expect(sentence!).toContain("acls.core1.PROTECT_SERVERS[3]");
  });

  it("returns null rather than inventing a sentence when the hop was decided by a route", () => {
    const t = traceFlow(DELIVERED);
    expect(t.outcome).toBe("delivered");
    expect(t.hops[0]!.decidedBy?.kind).toBe("route");
    expect(T2_blockingHop(t.hops[0]!)).toBeNull();
  });
});

describe("absence is never laundered into a value", () => {
  it("renders null as explicit words, not as an empty string", () => {
    const a = absence(null);
    expect(a.text).toBe("not observed");
    expect(a.text.length).toBeGreaterThan(0);
    expect(a.description).toMatch(/not a measurement of zero/i);
  });

  it("prefers the engine's own stated reason over the generic placeholder", () => {
    // riskUnobserved is the field that carries a REASON; trackingUnobserved is frequently the bare
    // marker. Pick the one that actually has prose, so this test proves the reason path, not the
    // fallback path.
    const real = fabric.l3.find((r) => (r.riskUnobserved ?? "").length > "[NOT OBSERVED]".length);
    expect(real, "the snapshot should contain at least one engine-stated absence WITH a reason").toBeDefined();
    const a = absence(real!.riskUnobserved);
    expect(a.hasReason).toBe(true);
    expect(a.text).toContain("show track");
    expect(a.text.startsWith("not observed — ")).toBe(true);
  });

  it("does not render a dangling separator when the marker carries no reason", () => {
    const a = absence("[NOT OBSERVED]");
    expect(a.hasReason).toBe(false);
    expect(a.text).toBe("not observed");
    expect(a.text).not.toMatch(/[—-]\s*$/);
  });

  it("treats 0 and false as MEASUREMENTS, not absences", () => {
    expect(resolveAbsence(0)).toBe(0);
    expect(resolveAbsence(false)).toBe(false);
    expect(resolveAbsence("")).toBe("");
    expect(isAbsence(resolveAbsence(null))).toBe(true);
    expect(isAbsence(resolveAbsence(undefined))).toBe(true);
  });
});

describe("the reserved-word gate", () => {
  it("catches an ASSERTED forbidden word", () => {
    expect(forbiddenWordsIn("this path is healthy")).toEqual(["healthy"]);
    expect(forbiddenWordsIn("the change is safe to apply")).toEqual(["safe"]);
    expect(forbiddenWordsIn("nothing to report")).toEqual([]);
  });

  it("does NOT flag a forbidden word inside a negated clause — that is the product stating limits", () => {
    // These two are verbatim shapes from the forwarding engine's real caveats. A gate that failed
    // them would push an author to delete an honest sentence in order to go green.
    expect(forbiddenWordsIn("nothing can be proven about forwarding on them")).toEqual([]);
    expect(forbiddenWordsIn("It does not show that ALL traffic does")).toEqual([]);
    expect(forbiddenWordsIn("this result is not a statement that the network is healthy")).toEqual([]);
  });

  it("matches whole words, so a disclaimer prefix is not read as its own opposite", () => {
    // Verbatim from the engine's caveat for a flow that reaches a host with no RIB.
    expect(forbiddenWordsIn("every statement about what happens at or beyond dist1 is unproven")).toEqual([]);
    expect(forbiddenWordsIn("this remains unverified")).toEqual([]);
    expect(forbiddenWordsIn("the change is unsafe")).toEqual([]);
    // ...but the bare word is still caught.
    expect(forbiddenWordsIn("this is proven")).toEqual(["proven"]);
  });

  it("does not let a negation leak across a clause boundary", () => {
    // The negation belongs to the first clause; the claim in the second is still an overclaim.
    expect(forbiddenWordsIn("we found no errors, so the link is healthy")).toEqual(["healthy"]);
    expect(forbiddenWordsIn("no counterexample was found. the path is safe")).toEqual(["safe"]);
  });

  it("emits no forbidden word in any generated claim over every suggested flow", () => {
    for (const s of suggestedFlows()) {
      const t = traceFlow(s.flow);
      const corpus = [T1_verdict(t), t.claim, sharePayload(t), ...t.caveats].join("\n");
      expect(forbiddenWordsIn(corpus), `forbidden word in the claim for ${s.id}`).toEqual([]);
    }
  });

  it("emits no forbidden word in the fixed template strings", () => {
    const fixed = [
      T10_SAMPLE_PATH,
      T8_coverageLine(),
      T4_unmodelledHost("dist1"),
      T3_outOfScope("198.51.100.7", ["10.0.10.0/24"]),
      absence(null).text,
      absence(null).description,
    ].join("\n");
    expect(forbiddenWordsIn(fixed)).toEqual([]);
  });

  it("the forbidden list is non-empty, so this suite cannot pass by having nothing to check", () => {
    expect(FORBIDDEN_CLAIM_WORDS.length).toBeGreaterThan(5);
  });
});

describe("a verdict cannot be quoted without its bounds", () => {
  it("the share payload carries claim, scope, caveats and provenance together", () => {
    const t = traceFlow(DENIED);
    const p = sharePayload(t);
    expect(p).toContain(t.claim);
    expect(p).toContain("SCOPE:");
    expect(p).toContain("core1");
    expect(p).toContain("CAVEATS");
    expect(p).toContain(fabric.meta.sourceSha256);
    expect(p).toContain(T10_SAMPLE_PATH);
  });

  it("every suggested flow's payload carries a non-empty caveat list", () => {
    for (const s of suggestedFlows()) {
      const t = traceFlow(s.flow);
      expect(t.caveats.length, `${s.id} produced an unqualified claim`).toBeGreaterThan(0);
      expect(sharePayload(t)).toContain("CAVEATS");
    }
  });
});

describe("the coverage line is read from the data", () => {
  it("reports the real numbers", () => {
    const line = T8_coverageLine();
    expect(line).toContain(`RIBs ${fabric.coverage.hostsWithRoutes}/${fabric.devices.length}`);
    expect(line).toContain(`ACLs ${fabric.coverage.hostsWithAcls}/${fabric.devices.length}`);
    expect(line).toContain(fabric.meta.sourceSha256.slice(0, 8));
  });
});

/**
 * Regression tests for the two defects the 2026-09-21 refuter confirmed in this module.
 *
 * Both FAILED before the fix, against this exact source: `claimBadge` returned `"SCOPED"` for the
 * empty trace, and `bandOfOutcome` / `bandOfHop` returned `undefined` for an unrecognised value.
 * Full method and the findings that were NOT defects are in `docs/refutation.md` (C1, C3).
 *
 * These are hand-built traces, which the header of this file otherwise forbids — deliberately, and
 * this is the exception that proves the rule. The real engine cannot currently produce either
 * input, and that is the whole point: both functions are EXPORTED and applied to whatever Trace a
 * caller holds, so "our engine happens not to emit this" is an assumption about a caller, not a
 * property of the function. A refuter's job is to stop an assumption being load-bearing.
 */
describe("REFUTED: the strongest badge cannot be earned by an empty traversal", () => {
  const empty = (over: Partial<Trace> = {}): Trace => ({
    flow: DELIVERED,
    outcome: "delivered",
    hops: [],
    claim: "",
    caveats: [],
    unmodelledHosts: [],
    elapsedMs: 0,
    ...over,
  });

  it("bands a delivered trace with no hops as INDETERMINATE, not SCOPED", () => {
    /* Before the fix this returned "SCOPED": every check in `claimBadge` was a check for a
       DISQUALIFIER, and `[].every(…)` is vacuously true. A traversal that touched nothing scored
       the product's strongest claim. */
    expect(claimBadge(empty())).toBe("INDETERMINATE");
  });

  it("changes no real trace's badge, because the new guard is unreachable for all of them", () => {
    /* The honest non-regression claim, stated as the PROPERTY that makes it true rather than as a
       list of badges that would have to be updated by hand.
       The fix adds exactly one branch, taken only when `hops.length === 0`. So: assert that no
       flow the product itself offers produces an empty traversal, and the branch provably cannot
       have altered any of their badges. Measured, not assumed — the denied flow on this snapshot
       already bands INDETERMINATE (it carries indeterminate ACL evidence), which is why pinning
       "not INDETERMINATE" would have been a false non-regression test rather than a real one. */
    const all = [traceFlow(DENIED), traceFlow(DELIVERED), ...suggestedFlows().map((s) => traceFlow(s.flow))];
    let empties = 0;
    for (const t of all) {
      if (t.hops.length === 0) {
        empties++;
        /* MEASURED, and it changed this test. The product's own suggested flow
           198.51.100.7 → 10.0.30.10 DOES produce an empty traversal, so "no real trace is empty"
           would have been a false statement dressed as a non-regression test. What is actually
           true is narrower and checkable: every real empty traversal carries an outcome that
           `claimBadge` answers BEFORE reaching the new guard, so the guard cannot have moved it.
           This also raises the stakes on C1 rather than lowering them — emptiness is reachable
           here, and the only thing that kept it off the SCOPED path was an outcome the engine
           happened to set. */
        expect(["out-of-scope", "indeterminate"], `${JSON.stringify(t.flow)}`).toContain(t.outcome);
      }
      // ...and the badge is one of the four, never undefined.
      expect(["SCOPED", "PARTIAL", "INDETERMINATE", "OUT OF SCOPE", "INVALID INPUT"]).toContain(claimBadge(t));
    }
    expect(all.length).toBeGreaterThan(2);
    // The empty case is not theoretical on this snapshot. If that stops being true, say so here.
    expect(empties).toBeGreaterThan(0);
  });
});

describe("REFUTED: an unrecognised verdict bands as UNDETERMINED, never as nothing", () => {
  /* Before the fix both switches fell off the end and returned `undefined`, which a renderer draws
     as a blank band — a verdict with no band reads as "nothing to say here". These values arrive
     from compiled snapshot JSON, so an unanticipated string is a runtime input. */
  it("bandOfOutcome", () => {
    expect(bandOfOutcome("recirculated" as never)).toBe("UNDETERMINED");
  });

  it("bandOfHop", () => {
    const hop = { ...traceFlow(DELIVERED).hops[0]!, verdict: "recirculated" as never };
    expect(bandOfHop(hop)).toBe("UNDETERMINED");
  });
});

/* ── C2 (docs/refutation.md; acceptance F3) ────────────────────────────────────
 * `claimBadge` used to read only the trace-level OUTCOME and the host-modelling coverage: a trace
 * saying "delivered" whose only hop said "loop" earned SCOPED, while `bandOfHop` on that same hop
 * said REFUTED. The badge now asks the hops, through `bandOfHop`, whether they support the outcome.
 *
 * Hand-built traces, for the reason the C1 block above states: the function is exported and applied
 * to whatever Trace a caller holds. The source is 10.0.30.1 — an address core1 owns, with no FHRP
 * alternate and no physical ingress port — so no ingress gap is computed and the ONLY thing that
 * differs between the control and the case is the hop verdict. The control proves the fixture really
 * reaches the SCOPED branch; without it, "not SCOPED" could pass for an unrelated reason.
 */
describe("REFUTED (C2): no outcome earns a stronger badge than its hops support", () => {
  const flow: Flow = { srcIp: "10.0.30.1", dstIp: "10.0.10.10", protocol: "tcp", dstPort: 443, srcPort: null };
  const hop = (verdict: Trace["hops"][number]["verdict"], index = 0): Trace["hops"][number] => ({
    index,
    host: "core1",
    outIntf: "Vlan10",
    nextHop: null,
    nextHost: null,
    verdict,
    decidedBy: null,
    evidence: [],
    alternatives: [],
  });
  const trace = (outcome: Trace["outcome"], hops: Trace["hops"]): Trace => ({
    flow,
    outcome,
    hops,
    claim: "",
    caveats: [],
    unmodelledHosts: [],
    elapsedMs: 0,
  });

  it("control: a delivered trace whose terminal hop is 'delivered' reaches SCOPED on this fixture", () => {
    expect(claimBadge(trace("delivered", [hop("delivered")]))).toBe("SCOPED");
    expect(bandOfTrace(trace("delivered", [hop("delivered")]))).toBe("RESOLVED");
  });

  it("a delivered trace whose only hop is a loop is not SCOPED and not RESOLVED", () => {
    const t = trace("delivered", [hop("loop")]);
    expect(bandOfHop(t.hops[0]!)).toBe("REFUTED");
    expect(claimBadge(t)).toBe("INDETERMINATE");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
  });

  it("every hop verdict that does not support 'delivered' at the end of the path withholds SCOPED", () => {
    const unsupporting = (["no-route", "denied", "loop", "ttl-exceeded", "unmodeled"] as const).filter((v) => bandOfHop(hop(v)) !== "RESOLVED");
    expect(unsupporting.length, "precondition: there are verdicts to check").toBe(5);
    for (const v of unsupporting) expect(claimBadge(trace("delivered", [hop(v)])), v).toBe("INDETERMINATE");
  });

  it("a refused hop BEFORE the end of the path undercuts a delivered outcome too", () => {
    expect(claimBadge(trace("delivered", [hop("denied", 0), hop("delivered", 1)]))).toBe("INDETERMINATE");
  });

  it("a denial is still a confidently answered question when its hops say denied", () => {
    // The tempting repair ("every hop must be RESOLVED") would turn this into INDETERMINATE.
    expect(claimBadge(trace("denied", [hop("forwarded", 0), hop("denied", 1)]))).toBe("SCOPED");
    expect(claimBadge(trace("denied", [hop("delivered")]))).toBe("INDETERMINATE");
    expect(claimBadge(trace("dropped", [hop("forwarded")]))).toBe("INDETERMINATE");
  });

  /* ── the empty-traversal rule (C1) and its owners ──
   * There used to be a dedicated line in `claimBadge`, `if (trace.hops.length === 0) return
   * "INDETERMINATE"`, and it was UNPINNED (acceptance report, F2): deleting it left every claims test
   * green. Measured, not guessed: for a DECIDED outcome word (delivered / denied / dropped) the same
   * zero-hop trace is also refused by `hopsSupportOutcome`, whose `last === undefined` check returns
   * false. The line was the only thing between an empty traversal and SCOPED for an UNRECOGNISED
   * outcome word (the C3 case) — until the 2026-09-22 probe below showed an unrecognised word earned
   * SCOPED over ORDINARY hops too, and the repair (no badge above INDETERMINATE for any word that
   * bands UNDETERMINED) covers the zero-hop case as well. The line then decided nothing on any input
   * and was removed. The two tests below pin the rule at its two remaining owners, and the sweep
   * after them pins it for every outcome word at once. This fixture is the no-ingress-gap source
   * above, so no policy gap can produce PARTIAL instead. */
  it("a delivered trace with ZERO hops is INDETERMINATE on the no-gap fixture, where only emptiness can withhold SCOPED", () => {
    const t = trace("delivered", []);
    expect(t.hops).toHaveLength(0);
    // Precondition: the same fixture with one delivered hop DOES reach SCOPED (control above), so the
    // withheld badge here is caused by the missing hop and nothing else.
    expect(claimBadge(trace("delivered", [hop("delivered")]))).toBe("SCOPED");
    expect(claimBadge(t)).toBe("INDETERMINATE");
    expect(hopsSupportOutcome(t), "the owner of the rule for decided words").toBe(false);
  });

  it("a ZERO-hop trace whose outcome word is unrecognised is INDETERMINATE — the outcome-band rule's case, hopsSupportOutcome does not decide it", () => {
    const t = trace("recirculated" as never, []);
    expect(bandOfOutcome(t.outcome), "precondition: an unrecognised word bands UNDETERMINED (C3)").toBe("UNDETERMINED");
    expect(hopsSupportOutcome(t), "precondition: hopsSupportOutcome does not refuse it, so only the outcome-band rule can").toBe(true);
    expect(claimBadge(t)).toBe("INDETERMINATE");
  });

  /* ── an outcome word this module does not recognise, over ORDINARY hops (2026-09-22 probe) ──
   * `hopsSupportOutcome` waves an unrecognised word through ("claims nothing, so nothing for the
   * hops to contradict"), `bandOfOutcome` bands it UNDETERMINED (C3) — and `claimBadge` then went on
   * to judge the TRAVERSAL: every host modelled, no policy gap, so SCOPED. The product's strongest
   * badge was awarded to a verdict word it cannot read, while the band beside it said UNDETERMINED:
   * the C2 shape (two parts of this module disagreeing about one trace, the badge taking the
   * flattering side) reached through the C3 door. Measured red before the fix: 'SCOPED'. */
  it("an unrecognised outcome word over a clean, fully-modelled traversal is INDETERMINATE, not SCOPED", () => {
    const clean = [hop("forwarded", 0), hop("delivered", 1)];
    // Control: the same hops under a word this module DOES read reach SCOPED, so the fixture is clean.
    expect(claimBadge(trace("delivered", clean))).toBe("SCOPED");
    const t = trace("recirculated" as never, clean);
    expect(bandOfOutcome(t.outcome), "precondition (C3)").toBe("UNDETERMINED");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(claimBadge(t)).toBe("INDETERMINATE");
  });

  it("no badge above INDETERMINATE for ANY outcome word whose band is UNDETERMINED, over no hop or any single hop", () => {
    /* The class, not the one word: every outcome whose band claims nothing (the two undecided words
       of the union, plus an unrecognised runtime value) against every hop verdict. Out-of-scope is
       its own badge; everything else must be INDETERMINATE — never SCOPED, never PARTIAL. */
    const words = ["indeterminate", "out-of-scope", "recirculated", ""] as const;
    const verdicts = ["forwarded", "delivered", "no-route", "denied", "loop", "ttl-exceeded", "unmodeled"] as const;
    for (const w of words) {
      expect(bandOfOutcome(w as never), `precondition: ${w} bands UNDETERMINED`).toBe("UNDETERMINED");
      for (const hops of [[], ...verdicts.map((v) => [hop(v)])]) {
        const badge = claimBadge(trace(w as never, hops));
        const over = hops.length === 0 ? "no hop" : `a ${hops[0]!.verdict} hop`;
        expect(badge, `${JSON.stringify(w)} over ${over}`).toBe(w === "out-of-scope" ? "OUT OF SCOPE" : "INDETERMINATE");
      }
    }
  });

  it("an EMPTY traversal earns no badge above INDETERMINATE under any outcome word at all", () => {
    /* C1 as a property over the whole word set, so neither owner of the rule can be removed without
       a red here: the decided words (hopsSupportOutcome's), the undecided words (the outcome-band
       rule's) and an unrecognised runtime value. */
    for (const w of ["delivered", "denied", "dropped", "indeterminate", "recirculated"] as const) {
      expect(claimBadge(trace(w as never, [])), `${w} with zero hops`).toBe("INDETERMINATE");
    }
    expect(claimBadge(trace("out-of-scope", []))).toBe("OUT OF SCOPE");
  });

  it("every real trace the product offers already satisfies the invariant, so the rule moves none of them", () => {
    const all = [traceFlow(DENIED), traceFlow(DELIVERED), traceFlow(NO_RIB), ...suggestedFlows().map((s) => traceFlow(s.flow))];
    const walked = all.filter((t) => t.hops.length > 0 && (t.outcome === "delivered" || t.outcome === "denied" || t.outcome === "dropped"));
    expect(walked.length, "precondition: real traces with a decided-looking outcome exist").toBeGreaterThan(0);
    for (const t of walked) expect(hopsSupportOutcome(t), JSON.stringify(t.flow)).toBe(true);
  });
});

describe("routeFieldReading — the one owner of how a route field reads (B1)", () => {
  const route = (over: Partial<import("./types").RouteEntry>): import("./types").RouteEntry => ({
    prefix: "10.0.0.0/24",
    source: "connected",
    nextHop: null,
    outIntf: "Vlan10",
    adminDistance: null,
    cite: "routes.x[0]",
    ...over,
  });

  it("reads each of the three states from the record's own fields", async () => {
    const { routeFieldReading, adminDistanceRank } = await import("./claims");
    const connected = routeFieldReading(route({}), "adminDistance");
    expect(connected.kind).toBe("not-applicable");
    expect(connected.text).toMatch(/^not recorded — /);
    expect(connected.text).not.toMatch(/^0\b/);
    const staticNull = routeFieldReading(route({ source: "static", nextHop: "10.0.0.1" }), "adminDistance");
    expect(staticNull).toMatchObject({ kind: "absent", text: "not observed", what: "administrative distance", why: expect.stringMatching(/did not record a distance/) });
    expect(routeFieldReading(route({ source: "static", adminDistance: 1 }), "adminDistance")).toMatchObject({ kind: "value", text: "1" });
    expect(routeFieldReading(route({ source: "local" }), "nextHop")).toMatchObject({ kind: "not-applicable", text: "n/a — a local route has no next hop" });
    // The ranking convention is decided here too, and a null static route has no rank.
    expect(adminDistanceRank(route({}))).toBe(0);
    expect(adminDistanceRank(route({ source: "static" }))).toBeNull();
    expect(adminDistanceRank(route({ source: "ospf", adminDistance: 110 }))).toBe(110);
  });

  it("every compiled route record's null reads the same through notApplicableReason as through the owner", async () => {
    const { routeFieldReading, notApplicableReason: na } = await import("./claims");
    const all = Object.values(fabric.routes).flat();
    expect(all.length).toBeGreaterThan(0);
    for (const r of all) {
      for (const f of ["adminDistance", "nextHop"] as const) {
        const reading = routeFieldReading(r, f);
        expect(na(r, f), `${r.cite}.${f}`).toBe(reading.kind === "not-applicable" ? reading.text : null);
      }
    }
  });
});
