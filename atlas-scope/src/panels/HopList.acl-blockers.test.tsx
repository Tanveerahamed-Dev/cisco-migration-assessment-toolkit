/**
 * HopList.acl-blockers.test.tsx — the hop card never calls an evaluable ACL line "cannot be evaluated"
 * (acceptance B5, re-grade 2026-10-03).
 *
 * The card composes its own "undecided" sentence from the line that decided the hop. It used to say
 * "ACL <list> line N on <host> cannot be evaluated for this flow" for EVERY undecided ACL decider. On
 * the real PROTECT_SERVERS a portless tcp flow is undecided because the flow leaves the destination port
 * of the evaluable `eq 443` / `eq 22` lines open — no line the model cannot read is involved — so that
 * sentence was false. The sweep below reads every undecided ACL hop the sample offers and checks the
 * sentence against `lineEvaluability` of the line it names, not against a list of known cases.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { resolveCite } from "../core/data";
import type { AclLine, Flow, Trace } from "../core/types";
import { lineEvaluability, traceFlow } from "../forwarding/engine";
import { GOLDEN_FORWARDING as G } from "../test-support/golden-expectations";
import { describeGolden } from "../test-support/golden-sample";
import { OUTSIDE_ADDRESSES, subnetHostAddresses } from "../test-support/trace-universe";
import { HopList } from "./HopList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

function reasonsOf(trace: Trace): { host: string; reason: string }[] {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(<HopList trace={trace} activeIndex={null} onSelect={() => {}} onOpenCite={() => {}} />));
  const out = [...el.querySelectorAll<HTMLElement>(".hop")].map((h) => ({
    host: h.querySelector(".hop__host")?.textContent ?? "",
    /* The card's own ACL sentence (composed from the decider), not a quoted gap sentence beside it. */
    reason:
      [...h.querySelectorAll("[data-undecided-reason]")]
        .map((r) => r.textContent ?? "")
        .find((t) => t.includes(ACL_SENTENCE_TAIL)) ?? "",
  }));
  act(() => root.unmount());
  el.remove();
  return out;
}

/** The tail HopList appends to the undecided sentence it composes from an ACL decider. */
const ACL_SENTENCE_TAIL = "the route below was decided; whether the packet passes was not";

const isAclLine = (v: unknown): v is AclLine => typeof v === "object" && v !== null && "index" in v && "raw" in v && "action" in v;

describe("an undecided hop's sentence uses the decider's true kind", () => {
  it("over every undecided ACL hop of a spread of flows (ip, portless tcp and udp, icmp)", () => {
    const addrs = [...new Set([...subnetHostAddresses().map((a) => a.ip), ...OUTSIDE_ADDRESSES])].sort();
    const services: [Flow["protocol"], number | null][] = [
      ["ip", null],
      ["tcp", null],
      ["udp", null],
      ["icmp", null],
    ];
    let checked = 0;
    let open = 0;
    const failures: string[] = [];
    for (const srcIp of addrs) {
      for (const dstIp of addrs) {
        if (srcIp === dstIp) continue;
        for (const [protocol, dstPort] of services) {
          const trace = traceFlow({ srcIp, dstIp, protocol, dstPort, srcPort: null });
          const deciders = trace.hops.filter((h) => h.verdict === "unmodeled" && h.decidedBy !== null && isAclLine(resolveCite(h.decidedBy.cite)));
          if (deciders.length === 0) continue;
          const reasons = reasonsOf(trace);
          for (const h of deciders) {
            const line = resolveCite(h.decidedBy!.cite) as AclLine;
            const reason = reasons.find((r) => r.host === h.host)?.reason ?? "";
            if (reason === "") continue; // the card states no model-owned reason on this hop
            checked += 1;
            const evaluable = lineEvaluability(line).evaluable;
            if (evaluable) open += 1;
            const says = reason.includes("cannot be evaluated");
            if (says === evaluable) failures.push(`${protocol} ${srcIp}->${dstIp} at ${h.host}: ${h.decidedBy!.cite} evaluable=${evaluable}: "${reason}"`);
          }
        }
      }
    }
    expect(failures.slice(0, 20), failures.slice(0, 20).join("\n")).toEqual([]);
    expect(checked, "the sweep reached undecided ACL hops").toBeGreaterThan(0);
    expect(open, "the sweep reached a hop left undecided by an evaluable line the flow leaves open").toBeGreaterThan(0);
  });
});

describeGolden("the refuter's portless tcp flow on core1's PROTECT_SERVERS", () => {
  it("says the flow leaves the destination port open, and does not call line 1 unevaluable", () => {
    const f = G.core1Acls.protectServers.blockerFlows.portlessTcp;
    const at = reasonsOf(traceFlow(f)).find((r) => r.host === G.core1Acls.host);
    expect(at?.reason ?? "").toContain("PROTECT_SERVERS line 1 of 4");
    expect(at?.reason ?? "").not.toContain("cannot be evaluated");
    expect(at?.reason ?? "").toContain("destination port");
  });
});
