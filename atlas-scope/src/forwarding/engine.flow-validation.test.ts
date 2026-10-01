/**
 * engine.flow-validation.test.ts — `traceFlow` answers only a question that is a flow.
 *
 * THE DEFECT (2026-09-23 acceptance report, B1). `traceFlow` checked the two addresses and nothing
 * else, so a `Flow` carrying `dstPort: NaN`, `70000` or `protocol: "bogus"` was walked through the
 * RIBs and ACLs and came back "a tcp/NaN flow from 10.0.10.50 to 10.0.20.10 is delivered at core1 on
 * connected route 10.0.20.0/24". The type says `number`; the value was not a port. The engine is the
 * last door every caller goes through (form, link, preset, counterexample, intent search), so it
 * refuses at ENTRY through the same validator the form and the link use (`flowProblems`,
 * src/forwarding/ip.ts): no verdict, no hops, and a claim that names the offending field.
 */
import { describe, expect, it } from "vitest";
import type { Flow } from "../core/types";
import { claimBadge, isInvalidInput } from "../core/claims";
import { refusalOf, traceFlow } from "./engine";

const base: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.20.10", protocol: "tcp", dstPort: 443, srcPort: null };

/* [label, flow, the field's words the claim must carry, the raw value it must quote]. The flows are
   built with casts on purpose: they are exactly the values a `Flow`-typed field held at runtime. */
const INVALID: readonly [string, Flow, RegExp, string][] = [
  ["NaN port", { ...base, dstPort: Number.NaN }, /destination port/, "NaN"],
  ["port 70000", { ...base, dstPort: 70000 }, /destination port/, "70000"],
  ["port 0", { ...base, dstPort: 0 }, /destination port/, "0"],
  ["port -1", { ...base, dstPort: -1 }, /destination port/, "-1"],
  ["port 1.5", { ...base, dstPort: 1.5 }, /destination port/, "1.5"],
  ["protocol bogus", { ...base, protocol: "bogus" as Flow["protocol"] }, /protocol/, "bogus"],
  ["empty protocol", { ...base, protocol: "" as Flow["protocol"] }, /protocol/, ""],
  ["a port on icmp", { ...base, protocol: "icmp", dstPort: 80 }, /destination port/, "80"],
  ["source port 70000", { ...base, srcPort: 70000 }, /source port/, "70000"],
  ["bad source address", { ...base, srcIp: "10.0.10" }, /source address/, "10.0.10"],
  ["bad destination address", { ...base, dstIp: "10.0.10" }, /destination address/, "10.0.10"],
];

describe("traceFlow refuses an invalid flow at entry", () => {
  for (const [label, flow, field, raw] of INVALID) {
    it(`${label}: no verdict, no hops, and the claim names the field`, () => {
      const t = traceFlow(flow);
      expect(["delivered", "denied", "dropped"]).not.toContain(t.outcome);
      expect(t.hops).toHaveLength(0);
      expect(isInvalidInput(t)).toBe(true);
      expect(claimBadge(t)).toBe("INVALID INPUT");
      expect(t.claim).toMatch(field);
      if (raw !== "") expect(t.claim).toContain(`"${raw}"`);
      expect(t.claim).not.toMatch(/\bis delivered\b|\bis denied\b/);
      expect(refusalOf(t)?.reason).toMatch(field);
    });
  }

  it("still traces the same flow with a valid port, and with its endpoints swapped", () => {
    for (const f of [base, { ...base, srcIp: base.dstIp, dstIp: base.srcIp }, { ...base, dstPort: null }, { ...base, protocol: "icmp" as const, dstPort: null }]) {
      const t = traceFlow(f);
      expect(isInvalidInput(t), JSON.stringify(f)).toBe(false);
    }
  });
});
