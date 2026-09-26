/**
 * store.flow-validation.test.ts — a shared link may only restore a flow the form would accept.
 *
 * THE DEFECT (2026-09-23 acceptance report, B1). `decodeInvestigation` built `out.flow` with
 * `dstPort: Number(dstPort)` and `protocol as Flow["protocol"]`, validating nothing. So
 * `?s=path&flow=10.0.10.50>10.0.20.10>tcp>abc` restored `dstPort: NaN` and the page said
 * "tcp 10.0.10.50 -> 10.0.20.10:NaN … is delivered at core1": a question no reader could have typed
 * into the form, answered as if it had been asked. Port 70000 and protocol `bogus` were traced the
 * same way. The form's own check (1–65535, whole number) lived only in PathTrace.tsx.
 *
 * THE RULE PINNED HERE. The link and the form go through ONE validator (`readFlow`, src/forwarding/
 * ip.ts). A flow it refuses is never written as `flow`: it is carried as `flowRefused`, with every
 * offending field NAMED, so the path panel can say what is wrong in words instead of tracing it.
 * Every valid link the encoder has ever written decodes to exactly the flow it did before.
 */
import { afterEach, describe, expect, it } from "vitest";
import { decodeInvestigation, encodeInvestigation, useInvestigation } from "./store";
import { readFlow } from "../forwarding/ip";

const decodeFlow = (flow: string) => decodeInvestigation(`s=path&flow=${encodeURIComponent(flow)}&hop=1`);

afterEach(() => useInvestigation.getState().reset());

describe("a shared link's flow is validated before it can be traced", () => {
  /* Each case: the flow text, the field that must be named, and the raw value the message must quote. */
  const REFUSED: readonly [string, string, string][] = [
    ["10.0.10.50>10.0.20.10>tcp>abc", "dstPort", "abc"],
    ["10.0.10.50>10.0.20.10>tcp>70000", "dstPort", "70000"],
    ["10.0.10.50>10.0.20.10>tcp>0", "dstPort", "0"],
    ["10.0.10.50>10.0.20.10>tcp>-1", "dstPort", "-1"],
    ["10.0.10.50>10.0.20.10>tcp>1.5", "dstPort", "1.5"],
    ["10.0.10.50>10.0.20.10>tcp>NaN", "dstPort", "NaN"],
    ["10.0.10.50>10.0.20.10>bogus>443", "protocol", "bogus"],
    ["10.0.10.50>10.0.20.10>>443", "protocol", ""],
    ["10.0.10.50>10.0.20.10", "protocol", ""],
    ["10.0.10.50>10.0.20.10>icmp>80", "dstPort", "80"],
    ["10.0.10>10.0.20.10>tcp>443", "srcIp", "10.0.10"],
    // The same bad address in the OTHER position must name the other field: a validator that only
    // looked at one side, or named the wrong one, fails here.
    ["10.0.20.10>10.0.10>tcp>443", "dstIp", "10.0.10"],
    ["10.0.10.0/24>10.0.20.10>tcp>443", "srcIp", "10.0.10.0/24"],
    [">10.0.20.10>tcp>443", "srcIp", ""],
    ["10.0.10.50>10.0.20.10>tcp>443>extra", "flow", "10.0.10.50>10.0.20.10>tcp>443>extra"],
  ];

  for (const [text, field, raw] of REFUSED) {
    it(`refuses ${JSON.stringify(text)} and names ${field}`, () => {
      const out = decodeFlow(text);
      expect(out.flow, "an invalid flow must never be restored as a flow to trace").toBeUndefined();
      expect(out.flowRefused?.text).toBe(text);
      const named = out.flowRefused?.problems.find((p) => p.field === field);
      expect(named, `no problem names ${field}: ${JSON.stringify(out.flowRefused?.problems)}`).toBeDefined();
      expect(named?.value).toBe(raw);
      // A hop names a hop of a trace; with no trace there is nothing for it to name.
      expect(out.hopIndex).toBeUndefined();
    });
  }

  it("names EVERY offending field, not only the first", () => {
    const out = decodeFlow("10.0.10>10.0.20>bogus>abc");
    expect(out.flowRefused?.problems.map((p) => p.field).sort()).toEqual(["dstIp", "dstPort", "protocol", "srcIp"]);
  });

  it("restores every flow the encoder writes exactly as before", () => {
    const VALID = [
      ["10.0.10.50>10.0.30.10>tcp>3389", { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null }],
      ["10.0.10.50>10.0.30.10>udp>53", { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "udp", dstPort: 53, srcPort: null }],
      ["10.0.10.50>10.0.30.10>tcp>", { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: null, srcPort: null }],
      ["10.0.10.50>10.0.30.10>icmp>", { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "icmp", dstPort: null, srcPort: null }],
      ["10.0.10.50>10.0.30.10>ip>", { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "ip", dstPort: null, srcPort: null }],
      // Swapped endpoints are a different, equally valid question.
      ["10.0.30.10>10.0.10.50>tcp>65535", { srcIp: "10.0.30.10", dstIp: "10.0.10.50", protocol: "tcp", dstPort: 65535, srcPort: null }],
    ] as const;
    for (const [text, flow] of VALID) {
      const out = decodeFlow(text);
      expect(out.flow, text).toEqual(flow);
      expect(out.flowRefused, text).toBeUndefined();
      expect(out.hopIndex, text).toBe(1);
      // And it round-trips through the encoder byte-for-byte.
      useInvestigation.getState().hydrate(out);
      expect(new URLSearchParams(encodeInvestigation(useInvestigation.getState())).get("flow")).toBe(text);
    }
  });

  it("keeps a refused flow in the link, so a reload shows the same refusal rather than dropping it", () => {
    const text = "10.0.10.50>10.0.20.10>tcp>abc";
    useInvestigation.getState().hydrate(decodeFlow(text));
    expect(new URLSearchParams(encodeInvestigation(useInvestigation.getState())).get("flow")).toBe(text);
  });

  it("clears the refusal the moment a real flow is set", () => {
    useInvestigation.getState().hydrate(decodeFlow("10.0.10.50>10.0.20.10>tcp>abc"));
    expect(useInvestigation.getState().flowRefused).not.toBeNull();
    useInvestigation.getState().setFlow({ srcIp: "10.0.10.50", dstIp: "10.0.20.10", protocol: "tcp", dstPort: 443, srcPort: null });
    expect(useInvestigation.getState().flowRefused).toBeNull();
  });

  it("goes through the same validator the form uses (one owner, two doors)", () => {
    /* The form feeds `readFlow` field text; the link feeds it the same fields split from the link.
       The same text must be judged the same way through both doors. */
    const viaLink = decodeFlow("10.0.10.50>10.0.20.10>tcp>70000").flowRefused?.problems;
    const direct = readFlow({ srcIp: "10.0.10.50", dstIp: "10.0.20.10", protocol: "tcp", dstPort: "70000" }).problems;
    expect(viaLink).toEqual(direct);
  });
});
