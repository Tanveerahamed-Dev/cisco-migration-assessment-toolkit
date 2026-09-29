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

import { hopUndecided } from "../core/claims";
import type { Flow, Trace } from "../core/types";
import { describeGolden } from "../test-support/golden-sample";
import { traceFlow } from "../forwarding/engine";
import { HopList } from "./HopList";
import { flowLabel, need, nonEmpty, universeTraces } from "./trace-universe";

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

/** How a trace's hops are decided — what the hop header and the decider block are drawn from. */
const deciderShape = (t: Trace): string =>
  `${t.outcome}|${t.hops.map((h) => `${h.host}:${h.verdict}:${h.decidedBy?.cite ?? "-"}:${hopUndecided(h, t) ?? "-"}`).join(">")}`;

const header = (hop: Element): string => hop.querySelector(".hop__head .verdict__word")?.textContent ?? "";
const decidedFacts = (hop: Element): Element[] => [...hop.querySelectorAll(".hop__fact[data-decided]")];
const factLabel = (fact: Element): string => (fact.querySelector(".hop__key")?.firstChild?.textContent ?? "").trim();

describe("A2: the hop header and the decider block agree about what decided the hop", () => {
  /* RE-EXPRESSED 2026-09-28 (phase 3). This pinned one flow, tcp 10.0.10.50 → 10.0.30.10:3389, whose
     denial was reached through core1's incomplete table ("… — reached by a route from an incomplete
     table"). The regenerated sample completed core1's table, so that hop is now undecided for a different
     reason — its outcome rests on an FHRP-alternate ingress ("refusal-undecided") — and its header read
     "denied — outcome not decided", naming NO agent above a block marked "ACL — this is what decided the
     hop". The class this test means is every reason a list-decided denial can be undecided, so the
     subjects are found by property: one denial per distinct undecided reason (and the decided one), each
     rendered in its own test. The exact flow is kept in the golden block below. */
  const subjects = (() => {
    const byReason = new Map<string, Trace>();
    for (const t of universeTraces()) {
      const last = t.hops[t.hops.length - 1];
      if (t.outcome !== "denied" || last === undefined || last.verdict !== "denied" || last.decidedBy?.kind !== "acl") continue;
      const why = hopUndecided(last, t) ?? "decided";
      if (!byReason.has(why)) byReason.set(why, t);
    }
    return [...byReason.entries()];
  })();

  it("the snapshot offers list-decided denials to check", (ctx) => {
    expect(need(ctx, nonEmpty(subjects), "denial decided by an ACL line").length).toBeGreaterThan(0);
  });

  it.each(subjects.map(([why, t]) => [`${why}: ${flowLabel(t.flow)}`, why, t] as const))("%s — the header names the deciding list", (_name, why, t) => {
    const last = t.hops[t.hops.length - 1]!;
    const aclName = /^acls\.[^.]+\.([^[]+)\[/.exec(last.decidedBy!.cite)?.[1];
    expect(aclName, `the deciding record ${last.decidedBy!.cite} names a list`).toBeDefined();
    const hop = [...render(t.flow).querySelectorAll(".hop")][t.hops.length - 1]!;
    /* Every subject's last hop is decided by an ACL line (the subject filter above). Two cases, each stated
       exactly (verifier V6: this had been loosened to "at most one", with the ACL checks made conditional):
       - the list is bound on this hop: EXACTLY one block is marked as the decider, the ACL naming the list;
       - no binding was observed ("binding-unobserved"): the list was chosen by the address-specificity rule,
         so it is drawn as "ACL · hypothesis", NO block is marked as the decider, and the header attributes
         the refusal to the list TEXT, never to "ACL <name>" as though the list were applied. */
    const decided = decidedFacts(hop);
    const word = header(hop);
    if (why === "binding-unobserved") {
      expect(decided.length, "a hypothesis is never marked as what decided the hop").toBe(0);
      const hypo = [...hop.querySelectorAll(".hop__fact")].filter((f) => factLabel(f) === "ACL · hypothesis");
      expect(hypo.length, "the list is drawn once, as a hypothesis").toBe(1);
      expect(hypo[0]!.textContent).toContain(aclName!);
      expect(word).toBe("denied by list text — binding unobserved");
      return;
    }
    expect(decided.length, "exactly one block is marked as the decider").toBe(1);
    expect(factLabel(decided[0]!), "the decider block is the ACL").toBe("ACL");
    expect(decided[0]!.textContent).toContain(`${aclName} line `);
    const agent = / by (ACL \S+|routing|list text)/.exec(word)?.[1] ?? null;
    expect(agent, "a list-decided hop is never headed as decided by routing").not.toBe("routing");
    if (agent !== null) expect(agent, "the header names no list but the deciding one").toBe(`ACL ${aclName}`);
    if (why !== "decided") {
      // An undecided header over the block that says a list decided the hop names that list …
      expect(word, "the header names the list the decided block names").toContain(`ACL ${aclName}`);
      // … and the half left undecided, whichever input left this denial open.
      expect(word).toMatch(/incomplete table|outcome not decided|binding unobserved|unobserved/);
    }
  });

  describeGolden("the refuter's flow", () => {
    it("tcp 10.0.10.50 → 10.0.30.10:3389 — PROTECT_SERVERS line 4 decided it, the header says so, and says the refusal is not decided", () => {
      const f: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null };
      const t = traceFlow(f);
      expect(t.outcome, "precondition: the real flow is a denial").toBe("denied");
      expect(t.hops[0]?.decidedBy?.cite, "precondition: the engine names PROTECT_SERVERS line 4").toBe("acls.core1.PROTECT_SERVERS[3]");
      // The refusal is undecided because the source can arrive by an FHRP-alternate ingress (the open half).
      expect(hopUndecided(t.hops[0]!, t), "precondition: the denial is left open by its ingress").toBe("refusal-undecided");
      const hop = render(f).querySelector(".hop")!;
      const decided = decidedFacts(hop);
      expect(decided.length).toBe(1);
      expect(factLabel(decided[0]!)).toBe("ACL");
      expect(decided[0]!.textContent).toContain("PROTECT_SERVERS line 4");
      const word = header(hop);
      expect(word).toBe("denied by ACL PROTECT_SERVERS — outcome not decided");
    });
  });

  /* One test per flow over the same denominator — one flow per decider shape of the subject universe —
     so the runner's timeout guards one rendered trace, not fifty (the EvidencePane
     per-finding policy, vitest.config.ts). The two "some hop was decided by…" preconditions are
     over the whole census, so each case tallies what it saw and the closing case asserts them,
     together with "every per-flow case ran": run this file whole, not one case of it. */
  describe("across every hop of every decider shape of the subject universe, a header never names a different agent than its decider", () => {
    /* UPDATED phase 3.5 (P3B-R2-m2): was every suggested flow plus a literal 3 × 5 × 3 grid of the sample's
       addresses. Now the first flow of each distinct decider shape of the universe (./trace-universe.ts:
       suggested flows first, then every SVI / FHRP / SVI-host / outside / routed pair), so the census is
       the class on whatever snapshot is loaded. */
    const flows: Flow[] = (() => {
      const byShape = new Map<string, Flow>();
      for (const t of universeTraces()) if (!byShape.has(deciderShape(t))) byShape.set(deciderShape(t), t.flow);
      return [...byShape.values()];
    })();
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

    /* ONE DENOMINATOR (phase 3.5, P3B-R2-m2): the census is the subject universe's decider shapes, not a
       literal source × destination grid of the sample's addresses. Every distinct way the universe's hops
       are decided (host, verdict, deciding record, undecided reason, per hop) is rendered once. */
    it("the census renders every decider shape of the subject universe", () => {
      const rendered = new Set(flows.map((f) => deciderShape(traceFlow(f))));
      const missing = [...new Set(universeTraces().map(deciderShape))].filter((k) => !rendered.has(k));
      expect(missing.slice(0, 8), `${missing.length} decider shapes the census never renders`).toEqual([]);
    });

    it("every per-flow case ran, and the census met both kinds of decider", (ctx) => {
      expect(flows.length, "precondition: the census has flows").toBeGreaterThan(0);
      expect(tally.flows, "every per-flow case above ran (run this file whole)").toBe(flows.length);
      /* Required on the reference sample; on another snapshot a decider kind it never produces is named. */
      need(ctx, tally.routeDecided > 0 ? tally.routeDecided : undefined, "hop decided by a route");
      need(ctx, tally.aclDecided > 0 ? tally.aclDecided : undefined, "hop decided by an ACL line");
    });
  });
});
