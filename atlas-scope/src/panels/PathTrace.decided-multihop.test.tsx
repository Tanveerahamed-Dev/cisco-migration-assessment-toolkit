/**
 * PathTrace.decided-multihop.test.tsx — the path and hop surfaces over DECIDED multi-hop traces of the
 * REAL snapshot, and an undecided hop beside them.
 *
 * Why this file exists (phase 3, 2026-09-28). Until the sample was regenerated, no trace of the shipped
 * snapshot was decided and every trace was one hop, so every surface's decided branch ran only under a
 * counterfactual (decided-surfaces.counterfactual.test.tsx) and no surface had ever drawn a second hop
 * from real evidence. The regenerated sample routes the pod subnets through dist1 to core1, so a decided
 * two-hop delivery and a decided two-hop denial now exist in the real data. This file pins, on the real
 * engine over the real compiled snapshot with no mock:
 *
 *   - a decided multi-hop delivery: every hop RESOLVED, the card RESOLVED, the 3-D mark "delivered";
 *   - a decided multi-hop denial: forwarding hops RESOLVED, the denying hop REFUTED, the card REFUTED,
 *     the 3-D mark "blocked", and its counterexample's "Not established" line carries the record that
 *     decided the counterexample;
 *   - on each, EVERY hop's citation controls resolve in the Inspector and open exactly their record;
 *   - an undecided hop on a multi-hop trace reads neither pass nor fail: the undecided band, the
 *     undecided glyph, and no pass/fail word.
 *
 * Subjects are found BY PROPERTY in the snapshot's own flow universe (trace-universe.ts), so the tests
 * hold on any snapshot that has such traces and fail by name on one that does not. The exact flows and
 * records of the reference sample are pinned in the golden block at the end.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { describeGolden } from "../test-support/golden-sample";
import { bandOfHop, bandOfHopIn, bandOfTrace, hopUndecided, isDecidedOutcome } from "../core/claims";
import { decodeInvestigation, useInvestigation } from "../core/store";
import type { Cite, Hop, Trace } from "../core/types";
import { counterexample, isDefiniteDelivery, traceFlow } from "../forwarding/engine";
import { traceMarkOf } from "../fabric3d/Fabric3D";
import { ClaimCard } from "./ClaimCard";
import { HopList, HopVerdictBadge } from "./HopList";
import { resolveCitation } from "./Inspector";
import { PathTrace } from "./PathTrace";
import { firstTrace, flowLabel, flowOf, need, nonEmpty, pathSearch, tracesWhere } from "../test-support/trace-universe";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  act(() => {
    useInvestigation.getState().reset();
  });
});

const citeOf = (b: Element): string | null => /^Open source record (.+)$/.exec(b.getAttribute("aria-label") ?? "")?.[1] ?? null;
const citeControls = (el: Element): HTMLButtonElement[] =>
  [...el.querySelectorAll<HTMLButtonElement>("button.ui-cite")].filter((b) => citeOf(b) !== null);

/* ── the subjects, by property ─────────────────────────────────────────────── */

const decidedDelivery = (): Trace | undefined => firstTrace((t) => t.hops.length >= 2 && isDefiniteDelivery(t));
const decidedDenial = (): Trace | undefined =>
  firstTrace((t) => t.hops.length >= 2 && t.outcome === "denied" && isDecidedOutcome(t) && counterexample(t.flow, t).found);
/** A hop whose verdict word alone would pass or refuse, but which its trace leaves undecided. */
const undecidedIn = (h: Hop, t: Trace): boolean => bandOfHop(h) !== "UNDETERMINED" && bandOfHopIn(h, t) === "UNDETERMINED";
/** One multi-hop trace per distinct reason an undecided hop carries, so every undecided wording is drawn. */
const undecidedHopTraces = (): Trace[] => {
  const byReason = new Map<string, Trace>();
  for (const t of tracesWhere((x) => x.hops.length >= 2))
    for (const h of t.hops) {
      if (!undecidedIn(h, t)) continue;
      const why = hopUndecided(h, t) ?? "none";
      if (!byReason.has(why)) byReason.set(why, t);
    }
  return [...byReason.values()];
};

/**
 * Every hop of the rendered list carries at least one citation control, the hop's own deciding record is
 * among them, every control resolves in the Inspector, and clicking it opens exactly that record.
 */
function expectEveryHopCitationWorks(t: Trace): void {
  const opened: Cite[] = [];
  const c = mount(<HopList trace={t} activeIndex={null} onSelect={() => {}} onOpenCite={(x) => opened.push(x)} />);
  const hops = [...c.querySelectorAll<HTMLElement>(".hop")];
  expect(hops.length, flowLabel(t.flow)).toBe(t.hops.length);
  hops.forEach((el, i) => {
    const hop = t.hops[i]!;
    const controls = citeControls(el);
    expect(controls.length, `hop ${i + 1} (${hop.host}) shows a citation control`).toBeGreaterThan(0);
    const cites = controls.map(citeOf);
    expect(hop.decidedBy, `hop ${i + 1} (${hop.host}) names what decided it`).not.toBeNull();
    expect(cites, `hop ${i + 1} (${hop.host}) shows its deciding record`).toContain(hop.decidedBy!.cite);
    for (const b of controls) {
      const cite = citeOf(b)!;
      expect(resolveCitation(cite).kind, `hop ${i + 1}: ${cite}`).not.toBe("unresolved");
      opened.length = 0;
      act(() => b.click());
      expect(opened, `hop ${i + 1}: clicking ${cite}`).toEqual([cite]);
    }
  });
}

/* ── a decided multi-hop delivery ─────────────────────────────────────────── */

describe("a decided multi-hop delivery of the real snapshot", () => {
  it("every hop and the card are RESOLVED, and the 3-D mark is a delivery", (ctx) => {
    const t = need(ctx, decidedDelivery(), "a definite delivery over two or more hops");
    expect(bandOfTrace(t)).toBe("RESOLVED");
    const c = mount(
      <>
        <ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />
        <HopList trace={t} activeIndex={null} onSelect={() => {}} />
      </>,
    );
    expect(c.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("RESOLVED");
    expect(c.querySelector(".claim__outcome-word")?.textContent ?? "").not.toMatch(/not decided/);
    const hops = [...c.querySelectorAll<HTMLElement>(".hop")];
    expect(hops.length).toBe(t.hops.length);
    for (const h of hops) {
      expect(h.dataset["band"], h.textContent ?? "").toBe("RESOLVED");
      expect(h.querySelector<HTMLElement>(".verdict")!.dataset["band"]).toBe("RESOLVED");
    }
    expect(hops[hops.length - 1]!.dataset["verdict"]).toBe("delivered");
    for (const h of hops.slice(0, -1)) expect(h.dataset["verdict"]).toBe("forwarded");
    expect(traceMarkOf(t)?.kind).toBe("delivered");
  });

  it("every hop's citation controls resolve and open exactly their record", (ctx) => {
    expectEveryHopCitationWorks(need(ctx, decidedDelivery(), "a definite delivery over two or more hops"));
  });

  it("the Path surface itself draws every hop of it, RESOLVED", async (ctx) => {
    const t = need(ctx, decidedDelivery(), "a definite delivery over two or more hops");
    act(() => {
      useInvestigation.getState().hydrate(decodeInvestigation(pathSearch(t.flow)));
    });
    const c = mount(<PathTrace />);
    await actAsync(async () => {
      await new Promise<void>((r) => requestAnimationFrame(() => setTimeout(r, 0)));
      await new Promise<void>((r) => setTimeout(r, 0));
    });
    const hops = [...c.querySelectorAll<HTMLElement>(".pt-result .hop")];
    expect(hops.length).toBe(t.hops.length);
    for (const h of hops) expect(h.dataset["band"]).toBe("RESOLVED");
    expect(c.querySelector<HTMLElement>(".pt-result .claim")!.dataset["band"]).toBe("RESOLVED");
    for (const b of citeControls(c.querySelector(".pt-result")!))
      expect(resolveCitation(citeOf(b)!).kind, citeOf(b)!).not.toBe("unresolved");
  });
});

/* ── a decided multi-hop denial ───────────────────────────────────────────── */

describe("a decided multi-hop denial of the real snapshot", () => {
  it("the forwarding hops are RESOLVED, the denying hop REFUTED, the card REFUTED, and the 3-D mark blocked", (ctx) => {
    const t = need(ctx, decidedDenial(), "a decided denial over two or more hops with a counterexample");
    expect(bandOfTrace(t)).toBe("REFUTED");
    const c = mount(
      <>
        <ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />
        <HopList trace={t} activeIndex={null} onSelect={() => {}} />
      </>,
    );
    expect(c.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("REFUTED");
    const hops = [...c.querySelectorAll<HTMLElement>(".hop")];
    expect(hops.length).toBe(t.hops.length);
    const last = hops[hops.length - 1]!;
    expect(last.dataset["verdict"]).toBe("denied");
    expect(last.dataset["band"]).toBe("REFUTED");
    for (const h of hops.slice(0, -1)) {
      expect(h.dataset["verdict"]).toBe("forwarded");
      expect(h.dataset["band"]).toBe("RESOLVED");
    }
    expect(traceMarkOf(t)?.kind).toBe("blocked");
  });

  it("every hop's citation controls resolve and open exactly their record", (ctx) => {
    expectEveryHopCitationWorks(need(ctx, decidedDenial(), "a decided denial over two or more hops with a counterexample"));
  });

  /* The denial through the real Path surface too, as the delivery above (phase 3.5, P3B-R2-m3): the hop
     surface drew it, but <PathTrace/> hydrated from the URL had only ever mounted the delivery. */
  it("the Path surface itself draws every hop of it: the forwarding hops RESOLVED, the denying hop and the card REFUTED", async (ctx) => {
    const t = need(ctx, decidedDenial(), "a decided denial over two or more hops with a counterexample");
    act(() => {
      useInvestigation.getState().hydrate(decodeInvestigation(pathSearch(t.flow)));
    });
    const c = mount(<PathTrace />);
    await actAsync(async () => {
      await new Promise<void>((r) => requestAnimationFrame(() => setTimeout(r, 0)));
      await new Promise<void>((r) => setTimeout(r, 0));
    });
    const hops = [...c.querySelectorAll<HTMLElement>(".pt-result .hop")];
    expect(hops.length).toBe(t.hops.length);
    for (const h of hops.slice(0, -1)) {
      expect(h.dataset["verdict"]).toBe("forwarded");
      expect(h.dataset["band"]).toBe("RESOLVED");
    }
    expect(hops[hops.length - 1]!.dataset["verdict"]).toBe("denied");
    expect(hops[hops.length - 1]!.dataset["band"]).toBe("REFUTED");
    expect(c.querySelector<HTMLElement>(".pt-result .claim")!.dataset["band"]).toBe("REFUTED");
    const cites = citeControls(c.querySelector(".pt-result")!).map((b) => citeOf(b)!);
    expect(cites, "the denying record is a citation on the Path surface").toContain(t.hops[t.hops.length - 1]!.decidedBy!.cite);
    for (const cite of cites) expect(resolveCitation(cite).kind, cite).not.toBe("unresolved");
  });

  it("its counterexample is decided, headed as one, and BOTH lines of the pair carry the record that decided them", (ctx) => {
    const t = need(ctx, decidedDenial(), "a decided denial over two or more hops with a counterexample");
    const ce = counterexample(t.flow, t);
    if (!ce.found) throw new Error("precondition: the subject was chosen for a found counterexample");
    expect(isDecidedOutcome(ce.trace), "the offered flow is itself decided").toBe(true);
    const opened: Cite[] = [];
    const c = mount(<ClaimCard trace={t} counterexample={ce} onOpenCite={(x) => opened.push(x)} />);
    expect(c.textContent ?? "").toMatch(/Counterexample — the nearest flow that behaves differently/);
    const dds = [...c.querySelectorAll(".claim__pair dd")];
    expect(dds.length, "the Intended / Not established pair is drawn").toBe(2);
    const denying = t.hops[t.hops.length - 1]!.decidedBy!.cite;
    expect(ce.trace.hops.length, "the counterexample's own trace has hops").toBeGreaterThan(0);
    /* EVERY hop's deciding record, not only the last (phase 3.5, P3B-R2-m3): a multi-hop counterexample's
       outcome rests on the forwarding hops' routes as well as on the record that decided its last hop. */
    const counterDeciders = ce.trace.hops.map((h, i) => {
      expect(h.decidedBy, `counterexample hop ${i + 1} (${h.host}) names what decided it`).not.toBeNull();
      return h.decidedBy!.cite;
    });
    expect(citeControls(dds[0]!).map(citeOf), "Intended").toContain(denying);
    /* The "Not established" line states the counterexample's outcome, which rests on different records
       than the denial: those records are its citations, working like every other. */
    const notEstablished = citeControls(dds[1]!);
    for (const cite of counterDeciders) expect(notEstablished.map(citeOf), `Not established cites ${cite}`).toContain(cite);
    for (const b of notEstablished) {
      expect(resolveCitation(citeOf(b)!).kind).not.toBe("unresolved");
      opened.length = 0;
      act(() => b.click());
      expect(opened).toEqual([citeOf(b)]);
    }
  });
});

/* ── an undecided hop on a multi-hop trace ────────────────────────────────── */

describe("an undecided hop on a multi-hop trace reads neither pass nor fail", () => {
  it("wears the undecided band and glyph and no pass or fail word, for every reason a hop is left undecided", (ctx) => {
    const found = undecidedHopTraces();
    const subjects = need(ctx, nonEmpty(found), "multi-hop trace with a hop its trace leaves undecided");
    const undecidedGlyph = mount(<HopVerdictBadge verdict="unmodeled" />).querySelector(".verdict__glyph")!.outerHTML;
    let checked = 0;
    for (const t of subjects) {
      const c = mount(<HopList trace={t} activeIndex={null} onSelect={() => {}} />);
      [...c.querySelectorAll<HTMLElement>(".hop")].forEach((el, i) => {
        const hop = t.hops[i]!;
        if (!undecidedIn(hop, t)) return;
        checked += 1;
        expect(el.dataset["band"], hop.host).toBe("UNDETERMINED");
        const badge = el.querySelector<HTMLElement>(".hop__head .verdict")!;
        expect(badge.dataset["band"]).toBe("UNDETERMINED");
        expect(badge.querySelector(".verdict__glyph")!.outerHTML, "the pass/fail glyph on an undecided hop").toBe(undecidedGlyph);
        const word = badge.querySelector(".verdict__word")?.textContent ?? "";
        expect(word, "the undecided half is named in the header").toMatch(/incomplete|unobserved|not decided/);
        expect(word).not.toMatch(/\b(resolved|refuted)\b/i);
        expect(el.querySelector("[data-undecided-reason]")?.textContent ?? "", "the reason is stated").not.toBe("");
      });
    }
    expect(checked, "an undecided hop was rendered").toBeGreaterThanOrEqual(subjects.length);
  });
});

/* ── the reference sample's own subjects ──────────────────────────────────── */

describeGolden("the reference sample's decided multi-hop traces", () => {
  /* The reference flows are named here, not taken as "the first found": which decided flow the universe
     meets first depends on the order the engine's own suggestions take, which is not a property of the
     evidence. */
  it("tcp 10.0.40.50 -> 10.0.10.50:443 is a definite delivery over dist1 to core1, decided by each hop's route", () => {
    const t = traceFlow(flowOf("10.0.40.50", "10.0.10.50", "tcp", 443));
    expect(isDefiniteDelivery(t)).toBe(true);
    expect(t.hops.map((h) => `${h.host}:${h.verdict}:${h.decidedBy?.cite}`)).toEqual(["dist1:forwarded:routes.dist1[1]", "core1:delivered:routes.core1[2]"]);
  });

  it("tcp 10.0.40.50 -> 10.0.30.10:443 is a decided denial by PROTECT_SERVERS line 4, answered over another destination", () => {
    const t = traceFlow(flowOf("10.0.40.50", "10.0.30.10", "tcp", 443));
    expect(t.outcome).toBe("denied");
    expect(isDecidedOutcome(t)).toBe(true);
    expect(t.hops.map((h) => `${h.host}:${h.verdict}:${h.decidedBy?.cite}`)).toEqual(["dist1:forwarded:routes.dist1[3]", "core1:denied:acls.core1.PROTECT_SERVERS[3]"]);
    const ce = counterexample(t.flow, t);
    expect(ce.found && flowLabel(ce.flow)).toBe("tcp 10.0.40.50 -> 10.0.20.10:443");
    expect(ce.found && ce.trace.hops[ce.trace.hops.length - 1]?.decidedBy?.cite).toBe("routes.core1[4]");
  });

  it("the undecided hops include core2 forwarding from its incomplete table, and core1 forwarding over an unobserved ingress", () => {
    const seen = undecidedHopTraces().flatMap((t) =>
      t.hops.filter((h) => undecidedIn(h, t)).map((h) => `${h.host}:${h.verdict}:${hopUndecided(h, t)}`),
    );
    expect(seen).toEqual(expect.arrayContaining(["core2:forwarded:route-table-partial", "core1:forwarded:ingress-unobserved"]));
  });
});
