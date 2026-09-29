/**
 * PathTrace.claim-cites.test.tsx — every claim the Path surface displays carries the citation that
 * backs it, counted PER CLAIM (acceptance B6).
 *
 * The regression this pins: on `?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0` the sentence
 * "…an OSPF adjacency with 10.0.99.2 is FULL/DR, yet the table holds no OSPF route" was displayed
 * five times — the headline claim, the Filtering row, a caveat, the hop note and the live-region
 * announcement — and its citations (`routing_neighbors.core1.ospf[0]`, `protocol_assessability.rows[…]`)
 * zero times; the no-route flow's "240 received prefixes" the same. The model held every one of those
 * citations (`ribIncompleteness()` returns them); `ribIncompletenessSentence()` joined the labels and
 * dropped the cites, and every surface quoted the sentence. An earlier pass counted citations per
 * PAGE — the page had dozens — so a claim with none of its own passed (acceptance report, B6).
 *
 * So every check here is per claim: (a)–(c) on the refuter's own flows, per element that shows the
 * claim; (d) over every `suggestedFlows()` trace and a source × destination grid, per CLAUSE of every
 * claim, caveat and policy-gap sentence the engine writes, and per rendered prose element of the claim
 * card and hop list. Nothing is a fixture: the flows, the expected citations and the resolver are the
 * shipped ones.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { fabric } from "../core/data";
import { decodeInvestigation, useInvestigation } from "../core/store";
import type { Flow, Trace } from "../core/types";
import { counterexample, suggestedFlows, traceFlow, unobservedPolicyInputs } from "../forwarding/engine";
import { hopUndecided } from "../core/claims";
import { describeGolden } from "../test-support/golden-sample";
import { controlsIn, renderedOffenders, uncitedClauses, withoutScope } from "./claim-cites-support";
import { need, nonEmpty, pathSearch, universeTraces } from "./trace-universe";
import { formatIpv4, parseInterfaceAddress, parseIpv4 } from "../forwarding/ip";
import { ribHostsShownIncomplete, ribIncompleteness } from "../forwarding/rib-completeness";
import { ClaimCard, IntentClaimCard } from "./ClaimCard";
import { HopList } from "./HopList";
import { resolveCitation } from "./Inspector";
import { PathTrace, intentCatalog, runIntentSearch } from "./PathTrace";
import { citesIn } from "./cited-text";

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
  act(() => { useInvestigation.getState().reset(); });
});

async function mountPath(search: string): Promise<HTMLElement> {
  act(() => { useInvestigation.getState().reset(); });
  act(() => { useInvestigation.getState().hydrate(decodeInvestigation(search)); });
  const c = mount(<PathTrace />);
  /* The announcement and the split re-aim land a frame after the synchronous answer. */
  await actAsync(async () => {
    await new Promise<void>((r) => requestAnimationFrame(() => setTimeout(r, 0)));
    await new Promise<void>((r) => setTimeout(r, 0));
  });
  return c;
}

const hiddenText = (el: Element): boolean => el.closest(".visually-hidden, [aria-live]") !== null;

/** The innermost elements whose text shows `phrase` — one per place the claim is displayed. */
function showing(root: Element, phrase: string): Element[] {
  return [...root.querySelectorAll("*")].filter(
    (e) => (e.textContent ?? "").includes(phrase) && ![...e.children].some((k) => (k.textContent ?? "").includes(phrase)),
  );
}

/** The citations an element displays for its claim: controls on a visible surface; the citation
 *  text itself in a screen-reader announcement, which can hold no control. */
const citationsShownBy = (el: Element): string[] => (hiddenText(el) ? citesIn(el.textContent ?? "") : controlsIn(el));

/**
 * The refuter's check, per claim: the claim text is displayed N > 0 times, and every one of those N
 * displays carries every citation the model holds for it, each resolving in the Inspector.
 */
function expectEveryDisplayCited(root: Element, phrase: string, cites: readonly string[]): number {
  const shown = showing(root, phrase);
  expect(shown.length, `"${phrase}" is displayed`).toBeGreaterThan(0);
  expect(cites.length, `the model holds citations for "${phrase}"`).toBeGreaterThan(0);
  for (const el of shown) {
    const have = citationsShownBy(el);
    for (const c of cites) {
      expect(have, `<${el.tagName.toLowerCase()} class="${el.className}"> shows "${phrase}" without ${c}`).toContain(c);
    }
  }
  for (const c of cites) expect(resolveCitation(c).kind, c).not.toBe("unresolved");
  const withAll = shown.filter((el) => cites.every((c) => citationsShownBy(el).includes(c))).length;
  expect(withAll, `claim displayed ${shown.length}×, with its citations ${withAll}×`).toBe(shown.length);
  return shown.length;
}

/* ══ (a)–(c) the refuter's claims, found by property ════════════════════════
   RE-EXPRESSED 2026-09-28 (phase 3). (a) pinned "FULL/DR, yet the table" at core1 on tcp/3389
   10.0.10.50 → 10.0.30.10, (b) "240 received prefixes" on the no-route flow from core2's subnet, and (c)
   "No ACLs were collected for core2" on that same flow. The regenerated sample completed core1's table (so
   (a)'s reason no longer exists) and gave core2 a default route (so no suggested flow is dropped, and (b)
   and (c) had no flow to mount). The class each pinned is "a partial-table reason, and a no-ACL caveat,
   are displayed with their citations wherever a path shows them". The subjects are therefore found by
   property: every host the snapshot shows incomplete, on a path whose hop at that host is undecided BY
   that table; and every routable host with no collected ACLs, on a path through it. The refuter's exact
   records for this sample are pinned in the golden block. */

/** A trace with a hop at `host` that its partial table leaves undecided, preferring a multi-hop path. */
function partialTablePath(host: string): { trace: Trace; hop: number } | undefined {
  const hit = (t: Trace): number => t.hops.findIndex((h) => h.host === host && hopUndecided(h, t) === "route-table-partial");
  const t = universeTraces().find((x) => x.hops.length >= 2 && hit(x) >= 0) ?? universeTraces().find((x) => hit(x) >= 0);
  return t === undefined ? undefined : { trace: t, hop: hit(t) };
}

/** How many reason displays the suggested-flow pages quoted, counted by the test below (run this file whole). */
let presetQuotes: number | null = null;

describe("B6 (a)/(b): every reason a table is shown incomplete is displayed with its citations", () => {
  it("the snapshot shows some collected table incomplete", (ctx) => {
    expect(need(ctx, nonEmpty(ribHostsShownIncomplete()), "collected routing table shown incomplete").length).toBeGreaterThan(0);
  });

  for (const host of ribHostsShownIncomplete()) {
    it(`${host}: on a path through it, every display of every reason carries all of ${host}'s receipts`, async (ctx) => {
      const subject = need(ctx, partialTablePath(host), `path with a hop that ${host}'s partial table leaves undecided`);
      const reasons = ribIncompleteness(host);
      const cites = reasons.map((r) => r.cite);
      const c = await mountPath(pathSearch(subject.trace.flow, subject.hop));
      for (const r of reasons) {
        /* Displayed at least on the hop's reason, the claim card's caveat and the live announcement. */
        expect(expectEveryDisplayCited(c, r.label, cites), r.label).toBeGreaterThanOrEqual(3);
      }
    });
  }

  /* Was "the suggested icmp flow (core1) carries the core1 citations on each of its displays". On the
     regenerated sample no suggested flow's own hop is undecided by a partial table; what the presets now
     quote is the partial table of the FHRP ALTERNATE they may enter by ("… rests on a table the snapshot
     shows to be incomplete (protocol_assessability.rows[…])"). Every such sentence a preset's page shows
     carries its own record, on every display. */
  it("every suggested flow's page shows each partial-table sentence it quotes with that sentence's record", async () => {
    let quoted = 0;
    for (const s of suggestedFlows()) {
      const t = traceFlow(s.flow);
      const c = await mountPath(pathSearch(s.flow));
      for (const g of unobservedPolicyInputs(t)) {
        if (!(g.kind === "rib-partial" || /incomplete/.test(g.label))) continue;
        if (showing(c, g.label).length === 0) continue;
        quoted += 1;
        expectEveryDisplayCited(c, g.label, [g.cite]);
      }
      for (const m of mounted.splice(0)) {
        act(() => m.root.unmount());
        m.container.remove();
      }
    }
    /* Whether a preset quotes one at all is the engine's choice; the reference sample's count is pinned
       in the golden block below. */
    presetQuotes = quoted;
    expect(suggestedFlows().length, "the snapshot offers suggested flows").toBeGreaterThan(0);
  });
});

describe("B6 (c): 'No ACLs were collected for <host>' is displayed with its citation", () => {
  it("each display on a path through a routable host with no collected ACLs carries a resolving citation", async (ctx) => {
    const noAcl = fabric.coverage.routableHosts.filter((h) => !fabric.coverage.aclHosts.includes(h));
    const subject = need(
      ctx,
      universeTraces().find((t) => t.hops.some((h) => noAcl.includes(h.host)) && t.caveats.some((x) => noAcl.some((h) => x.includes(`No ACLs were collected for ${h}`)))),
      "path through a routable host with no collected ACLs that says so",
    );
    const host = noAcl.find((h) => subject.caveats.some((x) => x.includes(`No ACLs were collected for ${h}`)))!;
    const c = await mountPath(pathSearch(subject.flow));
    const shown = showing(c, `No ACLs were collected for ${host}`);
    expect(shown.length).toBeGreaterThan(0);
    for (const el of shown) {
      const have = citationsShownBy(el);
      expect(have.length, el.textContent ?? "").toBeGreaterThan(0);
      for (const cite of have) expect(resolveCitation(cite).kind, cite).not.toBe("unresolved");
    }
  });
});

describeGolden("B6 (a)–(c): the refuter's records on the reference sample", () => {
  it("core2's table is the one shown incomplete, for its three uncollected protocols and its EVPN peer's 240 prefixes", () => {
    expect(ribHostsShownIncomplete()).toEqual(["core2"]);
    const reasons = ribIncompleteness("core2");
    expect(reasons.map((r) => r.cite)).toEqual(
      expect.arrayContaining(["protocol_assessability.rows[129]", "protocol_assessability.rows[130]", "protocol_assessability.rows[131]", "overlay.core2.evpn_neighbors[0]"]),
    );
    expect(reasons.map((r) => r.label).join(" | ")).toMatch(/240 received prefixes/);
  });

  it("some suggested flow's page quotes a partial-table sentence, so the preset sweep above checked something", () => {
    expect(presetQuotes, "the preset sweep ran (run this file whole)").not.toBeNull();
    expect(presetQuotes).toBeGreaterThan(0);
  });

  it("the path through it is core2 forwarding from Vlan20's subnet, and core2 is the routable host with no ACLs", () => {
    const subject = partialTablePath("core2");
    expect(subject?.trace.hops[subject.hop]?.host).toBe("core2");
    expect(subject?.trace.flow.srcIp.startsWith("10.0.20.")).toBe(true);
    expect(fabric.coverage.routableHosts.filter((h) => !fabric.coverage.aclHosts.includes(h))).toEqual(["core2"]);
  });
});

/* ══ (d) the class ═════════════════════════════════════════════════════════ */

/* The per-clause checks (namesEvidence, clauses, uncitedClauses, withoutScope, PROSE, renderedOffenders)
   moved unchanged to claim-cites-support.ts on 2026-09-28 (phase 3), so the no-route counterfactual holds a
   dropped trace to exactly this rule. */

/** Every flow the suggestions pose, and a grid over the addresses the snapshot actually holds. */
function sweep(): Flow[] {
  const addrs = new Set<string>(["198.51.100.7", "8.8.8.8"]);
  for (const s of suggestedFlows()) {
    addrs.add(s.flow.srcIp);
    addrs.add(s.flow.dstIp);
  }
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (a === null) continue;
    addrs.add(formatIpv4(a.ip));
    addrs.add(formatIpv4((a.prefix.base + 50) >>> 0));
    if (r.vip !== null && parseIpv4(r.vip) !== null) addrs.add(r.vip);
  }
  const services: [Flow["protocol"], number | null][] = [
    ["tcp", 443],
    ["tcp", 3389],
    ["udp", 53],
    ["icmp", null],
  ];
  const out: Flow[] = suggestedFlows().map((s) => s.flow);
  for (const src of addrs)
    for (const dst of addrs)
      for (const [protocol, dstPort] of services) if (src !== dst) out.push({ srcIp: src, dstIp: dst, protocol, dstPort, srcPort: null });
  return out;
}

/** Every trace of the sweep, and one per distinct SHAPE (addresses and ports masked) for the rendered
 *  sweep, which mounts each shape once: the texts differ only in the addresses a clause quotes. */
function sweepTraces(): { all: Trace[]; shapes: Trace[] } {
  const all = sweep().map(traceFlow);
  const seen = new Map<string, Trace>();
  const mask = (s: string): string => s.replace(/\d+(?:\.\d+){3}(?:\/\d+)?/g, "IP").replace(/(tcp|udp)\/\d+/g, "$1/N").replace(/^(an?) \w+/, "");
  for (const t of all) {
    const key = [t.outcome, t.hops.map((h) => `${h.host}:${h.verdict}`).join(">"), mask(t.claim), ...t.caveats.map(mask)].join("\n");
    if (!seen.has(key)) seen.set(key, t);
  }
  return { all, shapes: [...seen.values()] };
}

describe("B6 (d): the class — every displayed claim and caveat carries a citation that resolves", () => {
  const { all: traces, shapes } = sweepTraces();

  /* RE-EXPRESSED 2026-09-28 (phase 3). This required all five outcomes. The regenerated sample gave every
     collected table a default route, so no trace of it is "dropped": the sweep cannot reach that outcome
     on the real data, and the dropped branch is held to this same per-clause rule in
     claim-honesty.no-route.counterfactual.test.tsx. The invariant is that the sweep covers every outcome
     the snapshot produces at all — the whole universe of flows — and the reference sample's exact set,
     with "dropped" absent, is pinned in the golden block so a sample that drops again is noticed. */
  it("the sweep covers every outcome the engine produces on this snapshot", () => {
    expect(traces.length).toBeGreaterThan(200);
    expect(shapes.length).toBeGreaterThan(20);
    const produced = new Set(universeTraces().map((t) => t.outcome));
    expect(new Set(shapes.map((t) => t.outcome))).toEqual(produced);
  });

  describeGolden("the outcomes of the reference sample", () => {
    it("every outcome but 'dropped', which the no-route counterfactual covers", () => {
      expect(new Set(shapes.map((t) => t.outcome))).toEqual(new Set(["delivered", "denied", "indeterminate", "out-of-scope"]));
    });
  });

  it("every clause of every engine claim, caveat and policy-gap sentence that names a device or an address carries a resolving citation", () => {
    const offenders = new Map<string, string>();
    for (const t of traces) {
      const texts = [withoutScope(t), ...t.caveats, ...unobservedPolicyInputs(t).map((g) => g.label)];
      for (const text of texts) for (const c of uncitedClauses(text)) offenders.set(c, `${t.flow.protocol} ${t.flow.srcIp} → ${t.flow.dstIp}:${t.flow.dstPort ?? ""}`);
    }
    expect([...offenders].map(([c, f]) => `${f} :: ${c}`)).toEqual([]);
  });

  it("every policy gap's own citation is written into the sentence that states it", () => {
    const offenders: string[] = [];
    for (const t of traces) for (const g of unobservedPolicyInputs(t)) if (!citesIn(g.label).includes(g.cite)) offenders.push(`${g.kind} ${g.host} [${g.cite}] :: ${g.label}`);
    expect([...new Set(offenders)]).toEqual([]);
  });

  /* Split so no one test carries the whole rendered sweep against the hang-detector timeout; the
     parts together cover every shape, and the count pin below proves none is skipped. */
  /* 8, not 4 (phase 3): the regenerated sample's multi-hop traces added shapes, and a quarter of them
     ran 13-40 s on a contended host against the 30 s hang detector. */
  const PARTS = 8;
  it("the rendered sweep's parts cover every shape exactly once", () => {
    const covered = Array.from({ length: PARTS }, (_, k) => shapes.filter((_, i) => i % PARTS === k).length).reduce((a, b) => a + b, 0);
    expect(covered).toBe(shapes.length);
  });
  it.each(Array.from({ length: PARTS }, (_, k) => k))("the claim card and hop list render each claim with its citations, on every traced shape (part %i)", (part) => {
    const offenders = new Set<string>();
    const mine = shapes.filter((_, i) => i % PARTS === part);
    expect(mine.length).toBeGreaterThan(0);
    for (const t of mine) {
      const card = mount(<ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />);
      const hops = mount(<HopList trace={t} activeIndex={0} onSelect={() => {}} />);
      for (const o of [...renderedOffenders(card), ...renderedOffenders(hops)]) offenders.add(o);
      for (const m of mounted.splice(0)) {
        act(() => m.root.unmount());
        m.container.remove();
      }
    }
    expect([...offenders]).toEqual([]);
  });

  it("the intent card renders every caveat, bound and collateral sentence with its citations", () => {
    const offenders = new Set<string>();
    const intents = intentCatalog();
    expect(intents.length).toBeGreaterThan(0);
    for (const intent of intents) {
      const v = runIntentSearch(intent);
      for (const text of [v.boundSentence, v.unmodelledSentence ?? "", ...v.caveats.map((c) => c.text)])
        for (const c of uncitedClauses(text)) offenders.add(`${intent.id} :: ${c}`);
      const card = mount(<IntentClaimCard verdict={v} />);
      for (const o of renderedOffenders(card)) offenders.add(`${intent.id} :: ${o}`);
    }
    expect([...offenders]).toEqual([]);
  });
});
