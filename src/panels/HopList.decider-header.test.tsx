/**
 * HopList.decider-header.test.tsx — the hop header names the same decider the "decided" block names.
 *
 * 2026-09-22 independent acceptance report (A2, known issue 12): over the real denied flow
 * tcp 10.0.10.50 → 10.0.30.10:3389 the hop header read "denied by routing — table incomplete" while
 * the block marked "this is what decided the hop" was PROTECT_SERVERS line 4 and the claim card
 * attributed the denial to the ACL. The header's agent was a fixed word per undecided reason; it now
 * reads the hop's own decider, the same `classify(hop.decidedBy)` the block renders from.
 *
 * Everything here is the real engine over the real compiled snapshot, rendered by the real component.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { Flow } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { HopList } from "./HopList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

function render(f: Flow): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<HopList trace={traceFlow(f)} activeIndex={null} onSelect={() => {}} />));
  return host;
}

const header = (hop: Element): string => hop.querySelector(".hop__head .verdict__word")?.textContent ?? "";
const decidedFacts = (hop: Element): Element[] => [...hop.querySelectorAll(".hop__fact[data-decided]")];
const factLabel = (fact: Element): string => (fact.querySelector(".hop__key")?.firstChild?.textContent ?? "").trim();

describe("A2: the hop header and the decider block agree about what decided the hop", () => {
  it("tcp 10.0.10.50 → 10.0.30.10:3389 — the ACL decided it, and the header says so", () => {
    const f: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null };
    const t = traceFlow(f);
    expect(t.outcome, "precondition: the real flow is a denial").toBe("denied");
    expect(t.hops[0]?.decidedBy?.cite, "precondition: the engine names PROTECT_SERVERS line 4").toBe("acls.core1.PROTECT_SERVERS[3]");

    const hop = render(f).querySelector(".hop")!;
    const decided = decidedFacts(hop);
    expect(decided.length, "precondition: exactly one block is marked as the decider").toBe(1);
    expect(factLabel(decided[0]!)).toBe("ACL");
    expect(decided[0]!.textContent).toContain("PROTECT_SERVERS line 4");

    const word = header(hop);
    expect(word).toContain("ACL PROTECT_SERVERS");
    expect(word).not.toMatch(/by routing/);
    // The undecided half is still named — the route that reached the list came from a partial table.
    expect(word).toMatch(/incomplete table/);
  });

  it("across every hop of every suggested flow and a source × destination grid, a header never names a different agent than its decider", () => {
    const flows: Flow[] = suggestedFlows().map((s) => s.flow);
    for (const srcIp of ["10.0.10.50", "10.0.20.10", "10.0.30.5"])
      for (const dstIp of ["10.0.10.10", "10.0.20.10", "10.0.30.10", "10.0.40.5", "10.0.99.10"])
        for (const dstPort of [22, 443, 3389]) flows.push({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });
    let aclDecided = 0;
    let routeDecided = 0;
    const bad: string[] = [];
    for (const flow of flows) {
      const el = render(flow);
      for (const hop of el.querySelectorAll(".hop")) {
        const word = header(hop);
        for (const fact of decidedFacts(hop)) {
          const label = factLabel(fact);
          if (label === "ACL") {
            aclDecided += 1;
            if (/by routing/.test(word)) bad.push(`${JSON.stringify(flow)}: "${word}" over an ACL decider`);
          }
          if (label === "Route") {
            routeDecided += 1;
            if (/by ACL/.test(word)) bad.push(`${JSON.stringify(flow)}: "${word}" over a route decider`);
          }
        }
      }
      document.body.innerHTML = "";
    }
    expect(aclDecided, "precondition: some hop was decided by an ACL").toBeGreaterThan(0);
    expect(routeDecided, "precondition: some hop was decided by a route").toBeGreaterThan(0);
    expect(bad).toEqual([]);
  });
});
