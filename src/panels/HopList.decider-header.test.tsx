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
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { Flow } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { HopList } from "./HopList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* WORK PER TEST, COUNTED (acceptance F2, 2026-09-24). The census below took 32.1 s on a loaded host
   against the 30 s limit: one test rendering every suggested flow and a 45-flow grid, each into a
   React root it never unmounted. A test's cost is bounded here by what it renders — at most ONE
   trace — rather than by how long a busy machine takes to render fifty. */
const MAX_RENDERS_PER_TEST = 1;
let rendersThisTest = 0;
const roots: Root[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount());
  document.body.innerHTML = "";
  const n = rendersThisTest;
  rendersThisTest = 0;
  expect(n, "rendered traces in one test").toBeLessThanOrEqual(MAX_RENDERS_PER_TEST);
});

function render(f: Flow): HTMLElement {
  rendersThisTest += 1;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  roots.push(root);
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

  /* One test per flow over the same denominator — every suggested flow plus the source × destination
     × port grid — so the runner's timeout guards one rendered trace, not fifty (the EvidencePane
     per-finding policy, vitest.config.ts). The two "some hop was decided by…" preconditions are
     over the whole census, so each case tallies what it saw and the closing case asserts them,
     together with "every per-flow case ran": run this file whole, not one case of it. */
  describe("across every hop of every suggested flow and a source × destination grid, a header never names a different agent than its decider", () => {
    const flows: Flow[] = suggestedFlows().map((s) => s.flow);
    for (const srcIp of ["10.0.10.50", "10.0.20.10", "10.0.30.5"])
      for (const dstIp of ["10.0.10.10", "10.0.20.10", "10.0.30.10", "10.0.40.5", "10.0.99.10"])
        for (const dstPort of [22, 443, 3389]) flows.push({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });
    const tally = { flows: 0, aclDecided: 0, routeDecided: 0 };

    it.each(flows.map((flow, i) => [`#${i} ${flow.protocol} ${flow.srcIp} → ${flow.dstIp}:${flow.dstPort ?? "*"}`, flow] as const))("%s", (_name, flow) => {
      const bad: string[] = [];
      const el = render(flow);
      for (const hop of el.querySelectorAll(".hop")) {
        const word = header(hop);
        for (const fact of decidedFacts(hop)) {
          const label = factLabel(fact);
          if (label === "ACL") {
            tally.aclDecided += 1;
            if (/by routing/.test(word)) bad.push(`${JSON.stringify(flow)}: "${word}" over an ACL decider`);
          }
          if (label === "Route") {
            tally.routeDecided += 1;
            if (/by ACL/.test(word)) bad.push(`${JSON.stringify(flow)}: "${word}" over a route decider`);
          }
        }
      }
      tally.flows += 1;
      expect(bad).toEqual([]);
    });

    it("every per-flow case ran, and the census met both kinds of decider", () => {
      expect(flows.length, "precondition: the census has flows").toBeGreaterThan(45);
      expect(tally.flows, "every per-flow case above ran (run this file whole)").toBe(flows.length);
      expect(tally.aclDecided, "precondition: some hop was decided by an ACL").toBeGreaterThan(0);
      expect(tally.routeDecided, "precondition: some hop was decided by a route").toBeGreaterThan(0);
    });
  });
});
