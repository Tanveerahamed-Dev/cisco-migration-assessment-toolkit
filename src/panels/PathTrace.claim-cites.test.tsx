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
import { fabric } from "../core/data";
import { decodeInvestigation, useInvestigation } from "../core/store";
import type { Flow, Trace } from "../core/types";
import { counterexample, scopeClauseOf, suggestedFlows, traceFlow, unobservedPolicyInputs } from "../forwarding/engine";
import { formatIpv4, parseInterfaceAddress, parseIpv4 } from "../forwarding/ip";
import { ribIncompleteness } from "../forwarding/rib-completeness";
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
  act(() => useInvestigation.getState().reset());
});

async function mountPath(search: string): Promise<HTMLElement> {
  act(() => useInvestigation.getState().reset());
  act(() => useInvestigation.getState().hydrate(decodeInvestigation(search)));
  const c = mount(<PathTrace />);
  /* The announcement and the split re-aim land a frame after the synchronous answer. */
  await act(async () => {
    await new Promise<void>((r) => requestAnimationFrame(() => setTimeout(r, 0)));
    await new Promise<void>((r) => setTimeout(r, 0));
  });
  return c;
}

const citeOf = (b: Element): string => (b.getAttribute("aria-label") ?? "").replace(/^Open source record /, "");
const controlsIn = (el: Element): string[] => [...el.querySelectorAll(".ui-cite")].map(citeOf);
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

/** The citations the model holds for the reason whose label contains `phrase`. */
function ribCitesFor(host: string, phrase: string): string[] {
  const reasons = ribIncompleteness(host);
  const named = reasons.find((r) => r.label.includes(phrase));
  expect(named, `${host}: a reason reading "${phrase}"`).toBeDefined();
  return reasons.map((r) => r.cite);
}

/* ══ (a) the first pass's own flow ══════════════════════════════════════════ */

describe("B6 (a): tcp/3389 10.0.10.50 → 10.0.30.10, hop 0 — the RIB-incompleteness claim", () => {
  it("every display of 'FULL/DR, yet the table' carries routing_neighbors.core1.ospf[0] and the protocol receipts", async () => {
    const cites = ribCitesFor("core1", "FULL/DR, yet the table");
    /* The refuter's own citations, pinned so a change in the evidence is seen, not absorbed. */
    expect(cites).toEqual(expect.arrayContaining(["routing_neighbors.core1.ospf[0]", "protocol_assessability.rows[123]", "protocol_assessability.rows[124]"]));
    const c = await mountPath("?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0");
    const n = expectEveryDisplayCited(c, "FULL/DR, yet the table", cites);
    /* The five places the refuter counted: headline, Filtering row, caveat, hop note, announcement. */
    expect(n).toBeGreaterThanOrEqual(5);
  });
});

/* ══ (b) the core2 claim: "240 received prefixes" ══════════════════════════ */

describe("B6 (b): the no-route flow from core2's subnet — '240 received prefixes'", () => {
  it("every display carries the EVPN peer's citation and core2's protocol receipts", async () => {
    const s = suggestedFlows().find((f) => f.expectedOutcome === "dropped");
    expect(s, "a suggested flow the engine drops").toBeDefined();
    const trace = traceFlow(s!.flow);
    expect(trace.hops[trace.hops.length - 1]?.host).toBe("core2");
    const cites = ribCitesFor("core2", "240 received prefixes");
    const f = s!.flow;
    const c = await mountPath(`?s=path&flow=${f.srcIp}>${f.dstIp}>${f.protocol}>${f.dstPort ?? ""}&hop=0`);
    expect(expectEveryDisplayCited(c, "240 received prefixes", cites)).toBeGreaterThanOrEqual(4);
  });

  it("the suggested icmp flow (core1) carries the core1 citations on each of its displays", async () => {
    const s = suggestedFlows().find((f) => f.flow.protocol === "icmp");
    expect(s, "a suggested icmp flow").toBeDefined();
    const f = s!.flow;
    const c = await mountPath(`?s=path&flow=${f.srcIp}>${f.dstIp}>icmp>&hop=0`);
    expectEveryDisplayCited(c, "FULL/DR, yet the table", ribCitesFor("core1", "FULL/DR, yet the table"));
  });
});

/* ══ (c) the core2 no-ACL caveat ═════════════════════════════════════════════ */

describe("B6 (c): 'No ACLs were collected for core2' is displayed with its citation", () => {
  it("each display on the no-route flow carries a resolving citation", async () => {
    const s = suggestedFlows().find((f) => f.expectedOutcome === "dropped")!;
    const f = s.flow;
    const c = await mountPath(`?s=path&flow=${f.srcIp}>${f.dstIp}>${f.protocol}>${f.dstPort ?? ""}&hop=0`);
    const shown = showing(c, "No ACLs were collected for core2");
    expect(shown.length).toBeGreaterThan(0);
    for (const el of shown) {
      const have = citationsShownBy(el);
      expect(have.length, el.textContent ?? "").toBeGreaterThan(0);
      for (const cite of have) expect(resolveCitation(cite).kind, cite).not.toBe("unresolved");
    }
  });
});

/* ══ (d) the class ═════════════════════════════════════════════════════════ */

/* What makes a clause a claim about THIS network rather than about the model: it names a collected
   device or an address. Read from the compiled fabric, never listed. */
const HOSTS = [...new Set(fabric.devices.map((d) => d.host))].sort((a, b) => b.length - a.length);
const HOST_RE = new RegExp(`(?<![\\w.-])(?:${HOSTS.map((h) => h.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})(?![\\w-])`);
const IPV4_RE = /(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w])/;
const namesEvidence = (clause: string): boolean => HOST_RE.test(clause) || IPV4_RE.test(clause);

/**
 * Sentences, then `;`-separated items — the unit a reader quotes, and the unit a citation backs. Only
 * punctuation OUTSIDE parentheses splits: a parenthetical is part of the clause it qualifies.
 */
function clauses(text: string): string[] {
  /* Citations are masked first so a dotted path never splits a clause. */
  const masked: string[] = [];
  let t = text;
  for (const c of citesIn(text)) t = t.replace(c, () => `\u0001${masked.push(c) - 1}\u0002`);
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (let i = 0; i < t.length; i += 1) {
    const ch = t[i]!;
    if (ch === "(") depth += 1;
    if (ch === ")") depth = Math.max(0, depth - 1);
    const next = t.slice(i + 1, i + 3);
    const boundary = depth === 0 && ((ch === ";" && /^\s/.test(next)) || (ch === "." && /^\s[A-Z"]/.test(next)));
    cur += ch;
    if (boundary) {
      out.push(cur);
      cur = "";
    }
  }
  out.push(cur);
  return out.map((s) => s.replace(/\u0001(\d+)\u0002/g, (_, i: string) => masked[Number(i)]!)).filter((s) => s.trim() !== "");
}

function uncitedClauses(text: string): string[] {
  return clauses(text).filter((c) => namesEvidence(c) && !citesIn(c).some((x) => resolveCitation(x).kind !== "unresolved"));
}

/**
 * A claim's scope clause is the coverage denominator (acceptance B2): it names the RIB hosts, and the
 * record behind it is the coverage matrix the card's own scope block cites beside it ("RIBs" row,
 * checked in the rendered sweep below). It is judged there, not here — counted here, its one
 * citation would vouch for every clause after it in the sentence, which is the per-page count again.
 */
function withoutScope(t: Trace): string {
  const scope = scopeClauseOf(t);
  return scope === null ? t.claim : t.claim.slice(scope.length);
}

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

  it("the sweep covers every outcome the engine produces", () => {
    expect(traces.length).toBeGreaterThan(200);
    expect(shapes.length).toBeGreaterThan(20);
    expect(new Set(shapes.map((t) => t.outcome))).toEqual(new Set(["delivered", "dropped", "denied", "indeterminate", "out-of-scope"]));
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

  /* The rendered side: every prose element of the claim card and the hop list. Each in-text
     citation is a working control (never inert text), and an element that names a device or an
     address shows at least one control that resolves. */
  const PROSE =
    ".claim__sentence, .claim__undetermined, .claim__scope-line, .claim__scope-list > li, .claim__caveats > li, .claim__counter-why, .claim__counter-none, .claim__reasons > li, .claim__pair dd, .hop__note, .hop__ev";

  function renderedOffenders(root: Element): string[] {
    const out: string[] = [];
    for (const el of root.querySelectorAll(PROSE)) {
      const text = el.textContent ?? "";
      const controls = controlsIn(el);
      for (const c of citesIn(text)) if (!controls.includes(c)) out.push(`inert citation ${c} :: ${text}`);
      if (namesEvidence(text) && !controls.some((c) => resolveCitation(c).kind !== "unresolved")) out.push(`no citation :: ${text}`);
    }
    return out;
  }

  /* Split so no one test carries the whole rendered sweep against the hang-detector timeout; the
     parts together cover every shape, and the count pin below proves none is skipped. */
  const PARTS = 4;
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
