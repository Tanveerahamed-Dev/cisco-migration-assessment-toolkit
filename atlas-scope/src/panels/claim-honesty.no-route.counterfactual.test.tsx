/**
 * claim-honesty.no-route.counterfactual.test.tsx — a drop for want of a route is decided only where the
 * table that has no route is complete, and every surface says which.
 *
 * Why a counterfactual (phase 3, 2026-09-28). These properties were pinned on the no-route drop of the
 * real sample — core2 had no default route, so "core2 Vlan20 to the internet" was dropped at core2, whose
 * table the snapshot shows incomplete. The regenerated sample gave core2 (and every other collected table)
 * a default route, so no trace of the real snapshot is dropped any more: the "dropped" branch of the
 * claims owner, the headline word, the hop header and the citation sweep would otherwise never run on real
 * evidence again. This file asks the engine the counterfactual question "what if no collected table held
 * a default route", with that ONE producer answered differently (every 0.0.0.0/0 entry is removed from the
 * compiled routes). Every other route, ACL line, binding, SVI and FHRP record — and every completeness
 * receipt — is the real compiled evidence; every assertion runs through the real engine and the real
 * components, and vitest isolates modules per file, so the counterfactual never reaches another test or
 * the product. Subjects are found by property in the counterfactual's own flow universe.
 *
 * Moved here, their assertions unchanged:
 *  - claim-honesty-b1.test.tsx "every no-route suggested flow at a host with an incomplete table bands
 *    UNDETERMINED" (now over every no-route drop of the universe, suggested or not);
 *  - claim-honesty-0922.test.tsx "the critic's case: … names the incomplete table in the claim, and the
 *    headline word is the undecided one";
 *  - PathTrace.claim-cites.test.tsx (d) for the "dropped" outcome: every clause that names evidence carries
 *    a resolving citation, in the engine's text and on the rendered card and hop list.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../core/data", async (orig) => {
  const actual = await orig<typeof import("../core/data")>();
  const f = actual.fabric;
  const routes = Object.fromEntries(Object.entries(f.routes).map(([h, rs]) => [h, rs.filter((r) => r.prefix !== "0.0.0.0/0")]));
  return { ...actual, fabric: { ...f, routes }, routesOf: (h: string) => routes[h] ?? [] };
});

import { bandOfTrace, isDecidedOutcome, undecidedOutcomeWord } from "../core/claims";
import { fabric, routesOf } from "../core/data";
import type { Trace } from "../core/types";
import { counterexample, unobservedPolicyInputs } from "../forwarding/engine";
import { ribIncompleteness, ribIncompletenessSentence } from "../forwarding/rib-completeness";
import { ClaimCard, outcomeWordOf } from "./ClaimCard";
import { HopList } from "./HopList";
import { renderedOffenders, uncitedClauses, withoutScope } from "../test-support/claim-cites-support";
import { flowLabel, need, nonEmpty, tracesWhere } from "../test-support/trace-universe";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: Root[] = [];
function mount(ui: ReactNode): HTMLElement {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(ui));
  mounted.push(root);
  return el;
}
afterEach(() => {
  for (const r of mounted.splice(0)) act(() => r.unmount());
  document.body.innerHTML = "";
});

/** Every drop of the counterfactual universe that ended on a no-route hop. */
const noRouteDrops = (): Trace[] => tracesWhere((t) => t.outcome === "dropped" && t.hops[t.hops.length - 1]?.verdict === "no-route");
const endsAt = (t: Trace): string => t.hops[t.hops.length - 1]!.host;
const onIncomplete = (t: Trace): boolean => ribIncompleteness(endsAt(t)).length > 0;

describe("the counterfactual this file rests on", () => {
  it("no collected table holds a default route, every other route is kept, and the engine now drops", () => {
    for (const h of fabric.coverage.routableHosts)
      expect(
        routesOf(h).some((r) => r.prefix === "0.0.0.0/0"),
        h,
      ).toBe(false);
    expect(
      fabric.coverage.routableHosts.some((h) => routesOf(h).length > 0),
      "the rest of every table is real",
    ).toBe(true);
    expect(noRouteDrops().length, "the counterfactual produces no-route drops").toBeGreaterThan(0);
  });
});

describe("a drop on an incomplete routing table is not decided (claim-honesty-b1 #1)", () => {
  it("every no-route drop at a host with an incomplete table bands UNDETERMINED and names the partial table as a gap", (ctx) => {
    const drops = need(ctx, nonEmpty(noRouteDrops().filter(onIncomplete)), "no-route drop at a host whose table is shown incomplete");
    for (const t of drops) {
      expect(isDecidedOutcome(t), flowLabel(t.flow)).toBe(false);
      expect(bandOfTrace(t), flowLabel(t.flow)).toBe("UNDETERMINED");
      expect(
        unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial"),
        flowLabel(t.flow),
      ).toBe(true);
    }
  });

  it("a no-route drop at a host whose table is complete is not undecided BY the table", (ctx) => {
    /* The counterpart: the same "no route" read from a table the snapshot does NOT show incomplete never
       carries the partial-table gap, so a drop there is undecided only by some other input, if at all. */
    const drops = need(ctx, nonEmpty(noRouteDrops().filter((t) => !onIncomplete(t))), "no-route drop at a host whose table is complete");
    let decided = 0;
    for (const t of drops) {
      expect(
        unobservedPolicyInputs(t).some((g) => g.kind === "rib-partial" && g.host === endsAt(t)),
        flowLabel(t.flow),
      ).toBe(false);
      if (isDecidedOutcome(t)) {
        decided += 1;
        expect(bandOfTrace(t), flowLabel(t.flow)).toBe("REFUTED");
      }
    }
    expect(decided, "some drop at a complete table is decided").toBeGreaterThan(0);
  });
});

describe("an undecided drop is undecided in its own sentence (claim-honesty-0922 #3, the critic's case)", () => {
  it("names the incomplete table in the claim, and the headline word is the undecided one", (ctx) => {
    const t = need(ctx, noRouteDrops().find(onIncomplete), "no-route drop at a host whose table is shown incomplete");
    const at = endsAt(t);
    expect(t.claim).toMatch(new RegExp(`That drop is not decided: .*${at.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
    expect(t.claim).toMatch(/not a decided absence of a route/);
    expect(outcomeWordOf(t)).toBe(undecidedOutcomeWord(t));
    expect(outcomeWordOf(t)).toMatch(/^dropped for want of a collected route — not decided/);
    // The partial-table sentence the claim rests on is the owner's own, quoted — not paraphrased.
    expect(ribIncompletenessSentence(at)).not.toBeNull();
  });

  it("the card and the hop header draw it undecided, naming the incomplete table", (ctx) => {
    const t = need(ctx, noRouteDrops().find(onIncomplete), "no-route drop at a host whose table is shown incomplete");
    const c = mount(
      <>
        <ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />
        <HopList trace={t} activeIndex={null} onSelect={() => {}} />
      </>,
    );
    expect(c.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("UNDETERMINED");
    const last = [...c.querySelectorAll<HTMLElement>(".hop")].at(-1)!;
    expect(last.dataset["verdict"]).toBe("no-route");
    expect(last.dataset["band"]).toBe("UNDETERMINED");
    expect(last.querySelector(".hop__head .verdict__word")?.textContent).toBe("no route in the collected table — table incomplete");
  });
});

describe("every clause of a dropped trace carries a resolving citation (PathTrace.claim-cites (d), 'dropped')", () => {
  it("in the engine's claim, caveats and policy-gap sentences", (ctx) => {
    const drops = need(ctx, nonEmpty(noRouteDrops()), "no-route drop");
    const offenders = new Map<string, string>();
    for (const t of drops) {
      const texts = [withoutScope(t), ...t.caveats, ...unobservedPolicyInputs(t).map((g) => g.label)];
      for (const text of texts) for (const c of uncitedClauses(text)) offenders.set(c, flowLabel(t.flow));
    }
    expect([...offenders].map(([c, f]) => `${f} :: ${c}`)).toEqual([]);
  });

  it("on the rendered card and hop list, for one drop per host it ends at", (ctx) => {
    const byHost = new Map<string, Trace>();
    for (const t of noRouteDrops()) if (!byHost.has(endsAt(t))) byHost.set(endsAt(t), t);
    const drops = need(ctx, nonEmpty([...byHost.values()]), "no-route drop");
    const offenders = new Set<string>();
    for (const t of drops) {
      const card = mount(<ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />);
      const hops = mount(<HopList trace={t} activeIndex={0} onSelect={() => {}} />);
      for (const o of [...renderedOffenders(card), ...renderedOffenders(hops)]) offenders.add(`${flowLabel(t.flow)} :: ${o}`);
    }
    expect([...offenders]).toEqual([]);
  });
});
