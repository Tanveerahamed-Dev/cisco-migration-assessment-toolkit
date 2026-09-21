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
const DELIVERED: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null };
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
    for (const b of badges) expect(["SCOPED", "OBSERVED", "INDETERMINATE", "OUT OF SCOPE"]).toContain(b);
  });
});

describe("the verdict header states its own denominators", () => {
  it("names the real RIB coverage, read from the data and not hardcoded", () => {
    const line = T1_verdict(traceFlow(DENIED));
    expect(line).toContain(`${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length} hosts with a collected RIB`);
    // Guard against a future edit that inlines today's numbers as literals.
    expect(fabric.coverage.hostsWithRoutes).toBeLessThan(fabric.devices.length);
  });

  it("reports unmodelled hosts on the path rather than omitting them", () => {
    const t = traceFlow(NO_RIB);
    const s = scopeTuple(t);
    expect(s.unmodelledOnPath).toBeGreaterThan(0);
    expect(T1_verdict(t)).toContain("could not be modelled");
  });

  it("uses singular and plural correctly, because '1 hops' reads as a bug in the data", () => {
    const one = T1_verdict(traceFlow(DELIVERED));
    expect(one).toContain("traversed 1 hop across");
    expect(one).not.toContain("1 hops");
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
      expect(["SCOPED", "OBSERVED", "INDETERMINATE", "OUT OF SCOPE"]).toContain(claimBadge(t));
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
