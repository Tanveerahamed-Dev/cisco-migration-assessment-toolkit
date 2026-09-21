/**
 * PathTrace.test.tsx — the honesty regressions on the path-trace surface.
 *
 * Every test here runs against the REAL compiled snapshot and the real forwarding engine. None of
 * them shapes a fixture into the answer it wants: a hand-built trace would agree with whatever the
 * renderer does to it, and the defects worth catching on this surface are precisely the ones where
 * the renderer and the evidence disagree.
 *
 * The highest-value test in the file is `no counterexample found` carrying the unmodelled-hosts
 * sentence. A bare "no counterexample found" over partial data is the exact false-health claim this
 * whole product exists to prevent, and it is one deleted sentence away at any time.
 *
 * No testing-library, matching the rest of this project: React's own `act` over a real `createRoot`
 * in jsdom is enough.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode, act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Flow, Trace } from "../core/types";
import { counterexample, traceFlow } from "../forwarding/engine";
import { ClaimCard, IntentClaimCard } from "./ClaimCard";
import { HopList } from "./HopList";
import {
  PathTrace,
  intentCatalog,
  planIntent,
  runIntentSearch,
  validateFlowForm,
  type Intent,
} from "./PathTrace";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): { container: HTMLElement; render: (next: ReactNode) => void } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return { container, render: (next) => act(() => root.render(next)) };
}

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  act(() => useInvestigation.getState().reset());
});

/**
 * Let the SPLIT re-aim commit land.
 *
 * Running a flow paints the panel's own answer synchronously and hands the store write that
 * re-aims the other four surfaces to `requestAnimationFrame(() => setTimeout(..., 0))` — design
 * brief 8.3 rule 3, and the fix for J4 being the one journey over the 200 ms laboratory bar. So a
 * test that asserts on STORE state after clicking a preset or submitting the form has to wait one
 * frame plus one task; a test that asserts on what the PANEL shows does not, because that is the
 * half that is deliberately synchronous. Scheduling our own rAF and timeout behind the
 * component's is what orders this after it rather than guessing at a delay.
 */
async function settleCommit(): Promise<void> {
  await act(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}

const click = (el: Element): void => {
  act(() => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
};

const key = (el: Element, k: string): void => {
  act(() => el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })));
};

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  dstPort,
  srcPort: null,
});

/* The three flows below are the engine's own documented cases over this snapshot; each is asserted
   to still behave that way before it is used, so a data or engine change fails loudly here rather
   than quietly weakening a test into one that proves nothing. */
const DENIED = flow("10.0.10.50", "10.0.30.10", "tcp", 3389);
const INDETERMINATE = flow("10.0.10.50", "10.0.30.10", "icmp", null);
const UNMODELLED = flow("10.0.40.50", "10.0.30.10", "tcp", 443);

const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ");

describe("the data these tests rest on", () => {
  it("still produces the outcomes the assertions below assume", () => {
    expect(traceFlow(DENIED).outcome).toBe("denied");
    expect(traceFlow(INDETERMINATE).outcome).toBe("indeterminate");
    const unmod = traceFlow(UNMODELLED);
    expect(unmod.outcome).toBe("indeterminate");
    expect(unmod.unmodelledHosts.length).toBeGreaterThan(0);
    // Every claim on this surface is scoped by these; a hardcoded copy would rot silently.
    expect(fabric.coverage.hostsWithRoutes).toBeLessThan(fabric.devices.length);
  });
});

/* ══ the blocking hop ══════════════════════════════════════════════════════ */

describe("HopList — a denied flow", () => {
  const trace: Trace = traceFlow(DENIED);

  it("names the host, the ACL, the line index and the literal configuration text", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const body = text(container);
    expect(body).toContain("core1");
    expect(body).toContain("PROTECT_SERVERS");
    expect(body).toContain("line 3");
    // The literal line, verbatim — not a paraphrase of it.
    expect(container.querySelector(".hop__raw")?.textContent).toBe("deny ip any any");
  });

  it("marks the ACL row as the one that decided the hop, without hiding it behind a disclosure", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const decided = container.querySelector(".hop__fact[data-decided]");
    expect(decided).not.toBeNull();
    expect(text(decided)).toContain("PROTECT_SERVERS");
    // Disclosures are `hidden` when closed; the deciding evidence must not be inside a closed one.
    expect(decided?.closest("[hidden]")).toBeNull();
  });

  it("renders the beaten routes, with a null administrative distance as not observed", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const hop = trace.hops[0];
    expect(hop?.alternatives.length ?? 0).toBeGreaterThan(0);
    const alts = container.querySelector(".hop__alts");
    expect(alts).not.toBeNull();
    for (const alt of hop?.alternatives ?? []) expect(text(alts)).toContain(alt.prefix);
    // The winning route here is connected and carries no admin distance in the snapshot.
    expect(text(container.querySelector(".hop__facts"))).toContain("not observed");
  });

  it("gives every hop a citation control", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const cites = [...container.querySelectorAll(".ui-cite")];
    expect(cites.length).toBeGreaterThan(0);
    for (const c of cites) expect(c.getAttribute("aria-label") ?? "").toContain("Open source record");
  });
});

/* ══ the unmodelled hop — neither a pass nor a failure ═════════════════════ */

describe("HopList — a hop on a host with no RIB", () => {
  const trace = traceFlow(UNMODELLED);

  it("renders as UNDETERMINED with its own words, not as a pass and not as a failure", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const hop = container.querySelector(".hop");
    expect(hop?.getAttribute("data-verdict")).toBe("unmodeled");
    expect(hop?.getAttribute("data-band")).toBe("UNDETERMINED");
    expect(container.querySelectorAll('.hop[data-band="RESOLVED"]').length).toBe(0);
    expect(container.querySelectorAll('.hop[data-band="REFUTED"]').length).toBe(0);
    const body = text(container);
    expect(body).toContain("not modelled");
    expect(body).toContain("no routing table was collected");
    // The absence renderer, not a blank and not a dash.
    expect(container.querySelector(".ui-notobs")).not.toBeNull();
  });

  it("does not invent an egress or a next hop it could not have observed", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const body = text(container);
    expect(body).not.toContain("delivered");
    expect(body).not.toContain("forwarded");
  });
});

/* ══ hop selection drives the shared investigation state ══════════════════ */

describe("HopList — selection", () => {
  it("reports the hop index on click and on arrow traversal", () => {
    const trace = traceFlow(flow("10.0.10.50", "10.0.30.10", "tcp", 443));
    const seen: number[] = [];
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={(i) => seen.push(i)} />);
    const heads = [...container.querySelectorAll<HTMLButtonElement>(".hop__head")];
    expect(heads.length).toBe(trace.hops.length);
    click(heads[0]!);
    expect(seen).toContain(0);
    act(() => heads[0]!.focus());
    key(heads[0]!, "End");
    expect(seen[seen.length - 1]).toBe(trace.hops.length - 1);
  });
});

/* ══ the claim card ════════════════════════════════════════════════════════ */

describe("ClaimCard", () => {
  it("states the coverage denominators from the compiled snapshot, naming the hosts", () => {
    const trace = traceFlow(DENIED);
    const { container } = mount(<ClaimCard trace={trace} counterexample={counterexample(trace.flow, trace)} />);
    const body = text(container);
    const c = fabric.coverage;
    expect(body).toContain(`${c.hostsWithRoutes} of ${fabric.devices.length} hosts`);
    for (const h of c.routableHosts) expect(body).toContain(h);
    for (const h of c.aclHosts) expect(body).toContain(h);
    expect(body).toContain(fabric.meta.sourceSha256.slice(0, 8));
  });

  it("renders every caveat, with nothing collapsed", () => {
    const trace = traceFlow(INDETERMINATE);
    expect(trace.caveats.length).toBeGreaterThan(0);
    const { container } = mount(<ClaimCard trace={trace} />);
    const items = [...container.querySelectorAll(".claim__caveats > li")];
    expect(items.length).toBe(trace.caveats.length);
    for (const li of items) {
      // Nothing may sit inside a `hidden` subtree: a closed disclosure is a caveat nobody reads.
      expect(li.closest("[hidden]")).toBeNull();
    }
    expect(container.querySelectorAll(".claim .ui-disclosure").length).toBe(0);
  });

  it("gives an indeterminate outcome the same prominence as a denial, and says it is not an error", () => {
    const { container } = mount(<ClaimCard trace={traceFlow(INDETERMINATE)} />);
    const card = container.querySelector(".claim");
    expect(card?.getAttribute("data-band")).toBe("UNDETERMINED");
    // Same element, same heading level as any other verdict — not a muted note.
    expect(container.querySelector(".claim__outcome")?.tagName).toBe("H3");
    expect(text(container)).toContain("declined to decide");
    expect(text(container)).toContain("not a fault in the run");
  });

  it("offers the counterexample for a denied flow and can run it", () => {
    const trace = traceFlow(DENIED);
    const ce = counterexample(trace.flow, trace);
    expect(ce.found).toBe(true);
    const ran: Flow[] = [];
    const { container } = mount(
      <ClaimCard trace={trace} counterexample={ce} onRunFlow={(f) => ran.push(f)} />,
    );
    const btn = [...container.querySelectorAll("button")].find((b) =>
      (b.textContent ?? "").includes("Trace this flow instead"),
    );
    expect(btn).toBeDefined();
    click(btn!);
    expect(ran.length).toBe(1);
    expect(ran[0]?.dstPort).not.toBe(trace.flow.dstPort);
    // The two-part contract: what was shown, and what was NOT shown by it.
    expect(text(container)).toContain("Not established");
  });

  it("keeps the counterexample affordance when there is nothing to offer, carrying the reason", () => {
    const trace = traceFlow(DENIED);
    const { container } = mount(
      <ClaimCard
        trace={trace}
        counterexample={{ found: false, reason: "None of the 3 nearby variations traced as delivered." }}
      />,
    );
    expect(text(container)).toContain("None of the 3 nearby variations");
    expect(text(container)).toContain("Counterexample");
  });
});

/* ══ the form ══════════════════════════════════════════════════════════════ */

describe("validateFlowForm", () => {
  it("names precisely what is wrong and refuses to build a flow", () => {
    const bad = validateFlowForm({ srcIp: "10.0.10", dstIp: "", protocol: "tcp", dstPort: "99999" });
    expect(bad.flow).toBeNull();
    expect(bad.errors.srcIp).toContain("not an IPv4 address");
    expect(bad.errors.dstIp).toContain("Enter a source".replace("source", "destination"));
    expect(bad.errors.dstPort).toContain("outside the port range");
  });

  it("tells a reader who typed a subnet what to type instead", () => {
    const r = validateFlowForm({ srcIp: "10.0.10.0/24", dstIp: "10.0.30.10", protocol: "tcp", dstPort: "443" });
    expect(r.flow).toBeNull();
    expect(r.errors.srcIp).toContain("names a subnet");
  });

  it("drops the port for a protocol that has none, and keeps it for one that does", () => {
    const icmp = validateFlowForm({ srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "icmp", dstPort: "443" });
    expect(icmp.flow?.dstPort).toBeNull();
    const tcp = validateFlowForm({ srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: "443" });
    expect(tcp.flow?.dstPort).toBe(443);
  });
});

describe("PathTrace — running a flow", () => {
  it("does not write a malformed flow into the investigation state", () => {
    const { container } = mount(<PathTrace />);
    const form = container.querySelector("form");
    act(() => form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(useInvestigation.getState().flow).toBeNull();
    expect(text(container)).toContain("The flow was not run");
    // Focus lands on the first field that is wrong: an error the reader has to hunt for is an
    // error they will not read. Asserted because a broken ref would fail silently.
    const active = document.activeElement as HTMLElement | null;
    expect(active?.className).toContain("ui-input");
    expect(active?.getAttribute("aria-invalid")).toBe("true");
  });

  it("traces the flow the store carries, so a shared link reproduces the result", () => {
    const { container } = mount(<PathTrace />);
    act(() => useInvestigation.getState().setFlow(DENIED));
    const state = useInvestigation.getState();
    expect(state.trace?.outcome).toBe("denied");
    expect(text(container)).toContain("PROTECT_SERVERS");
    // The engine's own hop index is what the fabric highlights.
    expect(state.hopIndex).toBe(0);
  });

  /* ══ E2/E3: the re-aim commit stays SPLIT ═══════════════════════════════════════════════
     J4 was the one declared journey over the 200 ms laboratory bar (p95 224 ms, worst 384 ms,
     22 long tasks over 50 ms on its own interaction path) because one synchronous React commit
     re-aimed four surfaces from a single urgent store write. The panel now answers from local
     state in the interaction's own frame and hands the store write to a later task.

     This test pins BOTH halves, because either one alone is a different bug: a panel that does
     not answer synchronously is an unresponsive panel, and a store write that never lands is a
     trace the rest of the app never hears about. Merging them back into one commit — the
     regression this guards — fails the first assertion. */
  it("answers in the interaction's own frame and re-aims the other surfaces after it", async () => {
    const { container } = mount(<PathTrace />);
    const presets = [...container.querySelectorAll(".pt-preset__btn")];
    expect(presets.length).toBeGreaterThan(0);

    click(presets[0]!);
    // Synchronous half: the verdict and the hops are on screen already.
    expect(text(container)).toContain("Hops (");
    // Deferred half: the store — and so every other surface — has not been written yet.
    expect(useInvestigation.getState().flow).toBeNull();
    expect(useInvestigation.getState().trace).toBeNull();

    await settleCommit();
    const after = useInvestigation.getState();
    expect(after.flow).not.toBeNull();
    expect(after.trace).not.toBeNull();
    // The deferred write carries the SAME trace the panel already drew, not a second run of it.
    expect(after.trace?.flow.dstIp).toBe(after.flow?.dstIp);
    expect(text(container)).toContain("Hops (");
  });
  it("offers presets derived from the snapshot rather than an empty form", async () => {
    const { container } = mount(<PathTrace />);
    const presets = [...container.querySelectorAll(".pt-preset__btn")];
    expect(presets.length).toBeGreaterThan(0);
    click(presets[0]!);
    // The panel answers in the click's own frame; the store write that re-aims the other
    // surfaces is deliberately one frame behind it. See settleCommit.
    expect(text(container)).toContain("Hops (");
    await settleCommit();
    expect(useInvestigation.getState().flow).not.toBeNull();
  });
});

/* ══ the form survives being typed into ═══════════════════════════════════
 *
 * This describe block exists because every text field in this form used to destroy the panel on a
 * single keystroke, and nothing in this file noticed. The handlers read `e.currentTarget.value`
 * from INSIDE the `setForm` updater; an updater does not run when the event fires, and StrictMode
 * calls it a second time during render, by which point React has nulled `currentTarget`. The result
 * was `TypeError: Cannot read properties of null (reading 'value')` thrown mid-render and
 * `#rail-path` replaced by the error boundary. Measured 2026-09-21: one real keystroke into any of
 * Source IP / Destination IP / Destination port, or one change of Protocol, on the dev server.
 *
 * Production happened to survive, because StrictMode's double-invoke is development-only. That is
 * not a defence — React does not promise WHEN an updater runs — so these tests deliberately mount
 * under StrictMode, which is the configuration that exposes the fault. They fail against the old
 * handlers and pass against the current ones. */
describe("PathTrace — the flow form under StrictMode", () => {
  /** One character, delivered the way a browser delivers it: through React's own value tracker. */
  const typeChar = (el: HTMLInputElement, ch: string): void => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    act(() => {
      setter?.call(el, el.value + ch);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
  };

  const strictMount = (): HTMLElement =>
    mount(
      <StrictMode>
        <PathTrace />
      </StrictMode>,
    ).container;

  const fields = (container: HTMLElement): HTMLInputElement[] => [
    ...container.querySelectorAll<HTMLInputElement>("form.pt-form input"),
  ];

  it("survives one keystroke in every text field and keeps the character", () => {
    const container = strictMount();
    // The port field only exists for a ported protocol, which is the form's default (tcp).
    act(() => useInvestigation.getState().setFlow(DENIED));
    const inputs = fields(container);
    expect(inputs.length).toBe(3); // srcIp, dstIp, dstPort — a silent drop would weaken this test

    for (let n = 0; n < inputs.length; n++) {
      const input = fields(container)[n]!;
      const before = input.value;
      typeChar(input, "9");
      // Still mounted: the panel did not throw its way out of the tree.
      expect(container.querySelector("form.pt-form")).not.toBeNull();
      // And the keystroke actually landed, rather than being swallowed by a reset.
      expect(fields(container)[n]!.value).toBe(`${before}9`);
    }
  });

  it("survives a protocol change", () => {
    const container = strictMount();
    act(() => useInvestigation.getState().setFlow(DENIED));
    const select = container.querySelector<HTMLSelectElement>("form.pt-form select")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    act(() => {
      setter?.call(select, "udp");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(container.querySelector("form.pt-form")).not.toBeNull();
    expect(container.querySelector<HTMLSelectElement>("form.pt-form select")!.value).toBe("udp");
  });
});

/* ══ intent verification — the Batfish move ═══════════════════════════════ */

const catalog = intentCatalog();
const findIntent = (kind: Intent["kind"], predicate: (i: Intent) => boolean): Intent => {
  const found = catalog.find((i) => i.kind === kind && predicate(i));
  if (!found) throw new Error(`no ${kind} intent in the catalogue matched`);
  return found;
};

describe("intentCatalog", () => {
  it("is built from the snapshot: real subnets, real services, provenance on every address", () => {
    expect(catalog.length).toBeGreaterThan(0);
    for (const i of catalog) {
      expect(i.sources.length).toBeGreaterThan(0);
      expect(i.destinations.length).toBeGreaterThan(0);
      expect(i.services.length).toBeGreaterThan(0);
      for (const a of [...i.sources, ...i.destinations]) {
        expect(["observed", "derived"]).toContain(a.provenance);
        expect(a.cite.length).toBeGreaterThan(0);
      }
      // Every service names the ACL line it came from, so the search space is auditable.
      for (const s of i.services) expect(s.cite).toMatch(/^acls\./);
      expect(i.sourceSpace.usableHosts).toBeGreaterThanOrEqual(i.sourceSpace.enumerated);
    }
  });

  it("enumerates the same flow space on every run", () => {
    const a = planIntent(catalog[0]!).flows;
    const b = planIntent(catalog[0]!).flows;
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });
});

describe("runIntentSearch", () => {
  it("THE regression: a result with no counterexample always carries the unmodelled-hosts sentence", () => {
    const withoutRib = fabric.devices.length - fabric.coverage.hostsWithRoutes;
    expect(withoutRib).toBeGreaterThan(0);

    const clean = catalog.map((i) => runIntentSearch(i)).filter((v) => v.outcome === "no-counterexample-found");
    // The path must be exercised by the real data, or this test proves nothing.
    expect(clean.length).toBeGreaterThan(0);

    for (const v of clean) {
      expect(v.unmodelledSentence).not.toBeNull();
      expect(v.unmodelledSentence).toContain(String(withoutRib));
      expect(v.unmodelledSentence).toContain("could violate this intent");
      // And the bound sentence names the space it searched, not just the absence of a hit.
      expect(v.boundSentence).toContain(String(v.searched));
      expect(v.boundSentence).toContain(fabric.coverage.routableHosts[0]!);
    }
  });

  it("renders that sentence, not just computes it", () => {
    const verdict = catalog
      .map((i) => runIntentSearch(i))
      .find((v) => v.outcome === "no-counterexample-found");
    expect(verdict).toBeDefined();
    const { container } = mount(<IntentClaimCard verdict={verdict!} />);
    const body = text(container);
    expect(body).toContain("No counterexample was found");
    expect(body).toContain("could violate this intent");
    // The sentence is not tucked inside a collapsed region.
    const el = [...container.querySelectorAll("p")].find((p) =>
      (p.textContent ?? "").includes("could violate this intent"),
    );
    expect(el?.closest("[hidden]")).toBeNull();
  });

  it("finds a counterexample where one exists and makes it runnable", () => {
    const verdicts = catalog.map((i) => runIntentSearch(i));
    const found = verdicts.find((v) => v.outcome === "counterexample-found");
    expect(found).toBeDefined();
    const first = found!.counterexamples[0]!;
    expect(traceFlow(first.flow).outcome).toBe(first.trace.outcome);

    const ran: Flow[] = [];
    const { container } = mount(<IntentClaimCard verdict={found!} onRunFlow={(f) => ran.push(f)} />);
    const btn = [...container.querySelectorAll("button")].find((b) =>
      (b.textContent ?? "").includes("Open this flow in the trace view"),
    );
    click(btn!);
    expect(ran[0]).toEqual(first.flow);
  });

  it("never counts an undecided flow as consistent with the intent", () => {
    for (const i of catalog) {
      const v = runIntentSearch(i);
      expect(v.satisfying + v.counterexamples.length + v.undecided).toBe(v.searched);
      if (v.undecided > 0 && v.counterexamples.length === 0) expect(v.outcome).toBe("indeterminate");
      if (v.outcome === "no-counterexample-found") expect(v.undecided).toBe(0);
    }
  });

  it("reports an indeterminate space with a count and a reason for every undecided flow", () => {
    const v = catalog.map((i) => runIntentSearch(i)).find((r) => r.outcome === "indeterminate");
    expect(v).toBeDefined();
    expect(v!.undecided + v!.dropped).toBeGreaterThan(0);
    const counted = v!.undecidedReasons.reduce((n, r) => n + r.count, 0);
    expect(counted).toBe(v!.undecided + v!.dropped);
    const { container } = mount(<IntentClaimCard verdict={v!} />);
    expect(text(container)).toContain("could not be decided");
  });

  it("refuses to call a CAPPED search clean, and says how many it dropped", () => {
    // The cap is a real path, so it is exercised rather than asserted: an unexercised guard is not
    // a guard. Two flows out of spaces of dozens, over every intent in the catalogue — the
    // property is that NO capped search can come back clean, not that one particular one does not.
    for (const intent of catalog) {
      const capped = runIntentSearch(intent, 2);
      expect(capped.searched).toBe(2);
      expect(capped.dropped).toBeGreaterThan(0);
      expect(capped.outcome).not.toBe("no-counterexample-found");
      expect(capped.boundSentence).toContain(String(capped.dropped));
      expect(capped.collateral.join(" ")).toContain("says nothing whatever about them");
      const { container } = mount(<IntentClaimCard verdict={capped} />);
      expect(text(container)).toContain("were not traced");
    }
  });

  it("separates the intended effect from what else the search saw", () => {
    const v = runIntentSearch(findIntent("none-reach", () => true));
    expect(v.intendedEffect).toContain("The intent asserts");
    expect(v.collateral.length).toBeGreaterThan(0);
    expect(v.collateral.join(" ")).toContain("Outcomes inside the searched space");
    const { container } = mount(<IntentClaimCard verdict={v} />);
    expect(text(container)).toContain("Intended effect");
    expect(text(container)).toContain("Collateral");
  });

  it("produces byte-identical results on repeated runs", () => {
    const once = catalog.map((i) => runIntentSearch(i));
    const twice = catalog.map((i) => runIntentSearch(i));
    const strip = (v: (typeof once)[number]): unknown => ({
      outcome: v.outcome,
      bound: v.boundSentence,
      unmodelled: v.unmodelledSentence,
      counts: [v.searched, v.decided, v.undecided, v.satisfying, v.counterexamples.length],
      reasons: v.undecidedReasons.concat(v.decidedReasons),
      collateral: v.collateral,
    });
    expect(JSON.stringify(once.map(strip))).toBe(JSON.stringify(twice.map(strip)));
  });
});

/* ══ the chunked runner — acceptance E5 ═══════════════════════════════════
   The search is the one thing on this surface that can exceed the 200 ms interaction budget, so
   the chunk loop is the thing most worth exercising: it yields to the event loop, reports real
   progress, and can be cancelled. An unexercised guard is not a guard. */

describe("PathTrace — the chunked intent search", () => {
  const openIntentTab = (container: HTMLElement): void => {
    const tab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) =>
      (b.textContent ?? "").includes("Verify"),
    );
    click(tab!);
  };
  const button = (container: HTMLElement, label: string): HTMLButtonElement | undefined =>
    [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes(label));

  afterEach(() => {
    vi.useRealTimers();
  });

  it("yields between chunks, shows progress against a real denominator, and finishes", () => {
    vi.useFakeTimers();
    const { container } = mount(<PathTrace />);
    openIntentTab(container);
    click(button(container, "Search for a counterexample")!);

    // Nothing has been traced yet: the work is behind a yield, not on the click handler.
    const bar = container.querySelector('[role="progressbar"]');
    expect(bar).not.toBeNull();
    expect(bar?.getAttribute("aria-valuenow")).toBe("0");
    const total = Number(bar?.getAttribute("aria-valuemax"));
    expect(total).toBeGreaterThan(0);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const card = container.querySelector(".claim--intent");
    expect(card).not.toBeNull();
    // The verdict rendered by the UI is the verdict the headless search computes.
    expect(card?.getAttribute("data-intent-outcome")).toBe(runIntentSearch(catalog[0]!).outcome);
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  /* The progress UI is the part of this machinery that the shipped snapshot cannot exercise, and
   * "present but never exercised" is not an affordance. Measured 2026-09-21 in the browser: all
   * five intents in the catalogue complete in 65-83 ms over a flow space of 20-60, and sampling the
   * progressbar every 50 ms across a whole search returned ZERO distinct `aria-valuetext` values —
   * the bar never rendered long enough to be seen, so nothing had ever checked that the number it
   * shows advances, or that its text tracks it.
   *
   * The data cannot be made slower, but the CLOCK can be stopped. Stepping the fake timer one
   * chunk at a time puts the test where a user on slower data would be, and asserts the three
   * things the runtime could not: the value advances, it advances by the chunk size, and the
   * accessible text says the same thing as the number. */
  it("advances aria-valuenow one chunk at a time, with valuetext tracking it", () => {
    vi.useFakeTimers();
    const { container } = mount(<PathTrace />);
    openIntentTab(container);
    click(button(container, "Search for a counterexample")!);

    const read = (): { now: number | null; text: string | null; max: number | null } => {
      const bar = container.querySelector('[role="progressbar"]');
      if (bar === null) return { now: null, text: null, max: null };
      return {
        now: Number(bar.getAttribute("aria-valuenow")),
        text: bar.getAttribute("aria-valuetext"),
        max: Number(bar.getAttribute("aria-valuemax")),
      };
    };

    const total = read().max!;
    expect(total).toBeGreaterThan(12); // otherwise one chunk finishes it and this proves nothing

    const seen: number[] = [read().now!];
    const texts = new Set<string>([read().text!]);
    // Step one chunk per iteration until the bar goes away, with a hard stop so a hung search
    // fails this test rather than hanging it.
    for (let i = 0; i < 200; i++) {
      act(() => {
        vi.advanceTimersByTime(1);
      });
      const r = read();
      if (r.now === null) break;
      seen.push(r.now);
      texts.add(r.text!);
    }

    // Several distinct intermediate values, strictly increasing, none of them past the denominator.
    expect(seen.length).toBeGreaterThan(3);
    for (let i = 1; i < seen.length; i++) expect(seen[i]!).toBeGreaterThan(seen[i - 1]!);
    expect(seen[seen.length - 1]!).toBeLessThan(total);
    // The accessible text is not a static string: it carries the same number, and it changed.
    expect(texts.size).toBe(seen.length);
    for (const t of texts) expect(t).toMatch(/^\d+ of \d+ flows traced$/);
    expect([...texts].at(-1)).toBe(`${seen.at(-1)} of ${total} flows traced`);

    // And it still finishes, so the stepping above measured the real path rather than a stalled one.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(container.querySelector(".claim--intent")).not.toBeNull();
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  it("cancels mid-flight from a partially advanced bar, and keeps the partial count", () => {
    vi.useFakeTimers();
    const { container } = mount(<PathTrace />);
    openIntentTab(container);
    click(button(container, "Search for a counterexample")!);
    // Two chunks in: the bar is showing a real intermediate number when Cancel is pressed.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    act(() => {
      vi.advanceTimersByTime(1);
    });
    const midway = Number(
      container.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow"),
    );
    expect(midway).toBeGreaterThan(0);

    click(button(container, "Cancel the search")!);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    // No verdict from a partial search, and the partial count is reported rather than rounded away.
    expect(container.querySelector(".claim--intent")).toBeNull();
    const body = text(container);
    expect(body).toContain("No verdict is offered");
    expect(body).toContain(String(midway));
  });

  it("cancels without offering a verdict from a partial search", () => {
    vi.useFakeTimers();
    const { container } = mount(<PathTrace />);
    openIntentTab(container);
    click(button(container, "Search for a counterexample")!);
    act(() => {
      vi.advanceTimersByTime(0);
    });
    click(button(container, "Cancel the search")!);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(container.querySelector(".claim--intent")).toBeNull();
    expect(text(container)).toContain("No verdict is offered");
  });

  it("does not let a retired search write its verdict into a different intent", () => {
    /* This used to read `if (catalog.length < 2) return;` — a silent pass. The guard being tested
       is the one that stops a retired async search from writing its answer onto a DIFFERENT claim,
       so a catalogue that shrank to one intent would retire the only test of it while still
       reporting green. Assert the precondition instead of bailing on it. */
    expect(
      catalog.length,
      "this test needs two intents to switch between; a shrunken catalogue must fail, not skip",
    ).toBeGreaterThanOrEqual(2);
    vi.useFakeTimers();
    const { container } = mount(<PathTrace />);
    openIntentTab(container);
    click(button(container, "Search for a counterexample")!);
    act(() => {
      vi.advanceTimersByTime(0);
    });
    const select = container.querySelector<HTMLSelectElement>(".pt-intent select");
    act(() => {
      select!.value = catalog[1]!.id;
      select!.dispatchEvent(new Event("change", { bubbles: true }));
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    // The first intent's loop was retired: no card at all, rather than a card under the wrong claim.
    expect(container.querySelector(".claim--intent")).toBeNull();
    expect(text(container)).toContain(catalog[1]!.claim);
  });
});

/* ══ the form writes a field without destroying the panel ══════════════════
   Measured 2026-09-21 in a real browser: ONE keystroke into Source IP, Destination IP or
   Destination port — or one change of the Protocol select — replaced `#rail-path` with the error
   boundary on the dev server. The `onChange` handlers read `e.currentTarget.value` from INSIDE the
   `setForm` updater, and an updater does not run when the event fires; StrictMode deliberately
   invokes it a second time during render, by which point React has nulled `currentTarget`.
   Production happened to survive because that double-invoke is development-only — React makes no
   promise about when an updater runs, so it was luck. There was no test. Here is one. */

describe("PathTrace — one keystroke per control, under StrictMode", () => {
  const typeInto = (el: HTMLInputElement | HTMLSelectElement, value: string): void => {
    act(() => {
      const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      setter?.call(el, value);
      el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
    });
  };

  it("keeps the panel alive and records the value, for every control in the flow form", () => {
    const { container } = mount(
      <StrictMode>
        <PathTrace />
      </StrictMode>,
    );
    const inputs = [...container.querySelectorAll<HTMLInputElement>(".pt-form input")];
    expect(inputs.length, "the flow form must have text fields to type into").toBeGreaterThanOrEqual(3);

    for (const input of inputs) {
      const next = /port/i.test(input.id) ? "9" : "10.0.99.9";
      typeInto(input, next);
      expect(container.querySelector(".pt-form"), `the form vanished after typing into ${input.id}`).not.toBeNull();
      expect(input.value, `${input.id} did not take the typed value`).toBe(next);
    }

    const select = container.querySelector<HTMLSelectElement>(".pt-form select");
    if (select !== null) {
      const other = [...select.options].map((o) => o.value).find((v) => v !== select.value);
      if (other !== undefined) {
        typeInto(select, other);
        expect(container.querySelector(".pt-form")).not.toBeNull();
        expect(select.value).toBe(other);
      }
    }
  });

  it("no handler in this file captures the event inside a state updater", () => {
    /* The structural form of the bug, not the one instance of it. A behavioural test can only
       cover the controls that exist today; this covers the shape, so the next control added
       cannot reintroduce it. */
    const src = readFileSync(resolve(process.cwd(), "src/panels/PathTrace.tsx"), "utf8");
    const updaters = [...src.matchAll(/set[A-Z]\w*\(\s*\(\s*[\w$]*\s*\)\s*=>[\s\S]{0,240}?\n\s*\)/g)].map((m) => m[0]);
    const offenders = updaters.filter((b) => /currentTarget|\be\.target\b/.test(b));
    expect(
      offenders,
      "a functional state updater that reads the event runs AFTER React nulls currentTarget:\n" + offenders.join("\n---\n"),
    ).toEqual([]);
  });
});

/* ══ the announced verdict is the rendered verdict ═════════════════════════ */

describe("PathTrace — the intent verdict announcement", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  const openAndRun = (container: HTMLElement): void => {
    const tab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) =>
      (b.textContent ?? "").includes("Verify"),
    );
    click(tab!);
    click([...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes("Search for a counterexample"))!);
  };

  it("announces the unmodelled-hosts sentence, not only the bound sentence", () => {
    vi.useFakeTimers();
    const { container } = mount(<PathTrace />);
    openAndRun(container);
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    const verdict = runIntentSearch(catalog[0]!);
    expect(verdict.unmodelledSentence, "this intent must have an unmodelled bound to announce").not.toBeNull();

    const live = [...container.querySelectorAll('[aria-live="polite"]')].map((n) => text(n)).join(" ");
    expect(live).toContain(verdict.boundSentence);
    expect(live, "the only non-visual form of this verdict dropped its mandatory sentence").toContain(
      verdict.unmodelledSentence!,
    );
  });

  it("names the unmodelled hosts rather than only counting them, on every intent", () => {
    const withoutRib = fabric.devices.map((d) => d.host).filter((h) => !fabric.coverage.routableHosts.includes(h));
    expect(withoutRib.length).toBeGreaterThan(0);
    for (const i of catalog) {
      const v = runIntentSearch(i);
      if (v.unmodelledSentence === null) continue;
      const named = withoutRib.filter((h) => v.unmodelledSentence!.includes(h));
      expect(named.length, `${i.id} counted the unmodelled hosts but named none of them`).toBe(withoutRib.length);
    }
  });
});

/* ══ the >200 ms machinery is exercised, not merely present ════════════════
   E5's chunking, progress bar and cancel path were correct by inspection and unproven at runtime:
   the shipped flow space finishes in about 68 ms, so sampling the progressbar in a browser
   returned zero distinct values. Driving the chunk loop tick by tick is what turns an affordance
   into a tested one. */

describe("PathTrace — the chunk loop under a multi-chunk search", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  const startSearch = (): HTMLElement => {
    const { container } = mount(<PathTrace />);
    const tab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) =>
      (b.textContent ?? "").includes("Verify"),
    );
    click(tab!);
    click([...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes("Search for a counterexample"))!);
    return container;
  };

  const progress = (container: HTMLElement, attr: string): number | null => {
    const bar = container.querySelector('[role="progressbar"]');
    return bar === null ? null : Number(bar.getAttribute(attr));
  };

  it("advances aria-valuenow through several intermediate values before finishing", () => {
    vi.useFakeTimers();
    const container = startSearch();
    const total = progress(container, "aria-valuemax") ?? 0;
    expect(total, "the search must span more than one chunk for this to mean anything").toBeGreaterThan(12);

    const seen: number[] = [];
    for (let i = 0; i < 60 && container.querySelector('[role="progressbar"]') !== null; i++) {
      const v = progress(container, "aria-valuenow");
      if (v !== null && seen[seen.length - 1] !== v) seen.push(v);
      act(() => {
        vi.advanceTimersByTime(1);
      });
    }
    expect(seen[0]).toBe(0);
    expect(seen.length, `progress reported only ${seen.join(", ")}`).toBeGreaterThanOrEqual(3);
    for (let i = 1; i < seen.length; i++) expect(seen[i]!).toBeGreaterThan(seen[i - 1]!);
    expect(container.querySelector(".claim--intent")).not.toBeNull();
  });

  it("Cancel stops it MID-FLIGHT and the cancelled state refuses a verdict", () => {
    vi.useFakeTimers();
    const container = startSearch();
    // One chunk only: the search is genuinely part-way through, not finished.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    const done = progress(container, "aria-valuenow") ?? 0;
    const total = progress(container, "aria-valuemax") ?? 0;
    expect(done).toBeGreaterThan(0);
    expect(done).toBeLessThan(total);

    click([...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes("Cancel the search"))!);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(container.querySelector(".claim--intent"), "a cancelled search must not publish a verdict").toBeNull();
    expect(text(container)).toContain("No verdict is offered");
    expect(text(container)).toContain(`after ${done} of ${total} flows`);
  });
});

/* ══ a hop selection re-aims the other surfaces (acceptance A4) ═════════════ */

describe("PathTrace — selecting a hop re-aims the investigation", () => {
  it("selects the hop's own host, so the device pane and evidence rail follow it", () => {
    /* The store's `selectHop` writes `hopIndex` and nothing else. A4 names the hop as one of the
       four selections that must re-aim the others, and it did not: with device access13 selected
       and the denied trace open, clicking "Hop 1 of 1: core1 denied" left the device pane showing
       access13 ("Routing: no RIB collected") — the hop click led nowhere.
       Driven through the real component and the real engine: the assertion is on the STORE, which
       is what the device pane, the evidence rail and the fabric all read. */
    const { container } = mount(<PathTrace />);
    act(() => useInvestigation.getState().setFlow(DENIED));

    // Point every other surface somewhere else first, so "it followed the hop" is a real change
    // and not the state it already happened to hold.
    act(() => useInvestigation.getState().selectDevice("access13"));
    expect(useInvestigation.getState().deviceId).toBe("access13");

    const trace = useInvestigation.getState().trace;
    expect(trace).not.toBeNull();
    const heads = [...container.querySelectorAll<HTMLButtonElement>(".hop__head")];
    expect(heads.length).toBeGreaterThan(0);

    click(heads[0]!);

    const after = useInvestigation.getState();
    expect(after.hopIndex).toBe(0);
    // The hop's host, resolved through the snapshot rather than assumed equal to the hop string.
    const hopHost = trace?.hops[0]?.host;
    const device = fabric.devices.find((d) => d.id === hopHost || d.host === hopHost);
    expect(device).toBeDefined();
    expect(after.deviceId).toBe(device?.id);
    expect(after.deviceId).not.toBe("access13");
  });
});

/* ══ the strongest claim must carry the most caveats, not the fewest ═══════ */

/**
 * THE DEFECT. `IntentClaimCard` rendered no caveat list at all. "No counterexample found" — a
 * universal statement over a whole flow class, band RESOLVED — shipped with none of the bounds
 * that every single-flow trace card carries, while the same evidence on ONE flow rendered
 * "CAVEATS (11) — EVERY REASON THIS RESULT IS NARROWER THAN IT LOOKS". The weakest claim showed
 * eleven bounds; the strongest showed zero. The search's own constituent traces produced them
 * (FHRP ingress taken from a point-in-time HSRP observation, no `ip access-group` binding
 * collected anywhere, forward direction only, ECMP not modelled) and `stepIntentSearch` discarded
 * every one.
 *
 * Asserted as a class: for EVERY intent in the catalogue, the union of its traced flows' caveats
 * must appear on the verdict. A caveat that bounds one flow bounds a universal claim over a space
 * containing that flow at least as hard.
 */
describe("an intent verdict carries the union of its flows' caveats", () => {
  it.each(catalog.map((i) => i.id))("%s loses no caveat its searched flows produced", (id) => {
    const intent = catalog.find((i) => i.id === id)!;
    const plan = planIntent(intent);
    const v = runIntentSearch(intent);

    const expected = new Set<string>();
    for (const f of plan.flows) for (const c of traceFlow(f).caveats) expected.add(c);
    expect(expected.size, "this intent traced no flow that produced a caveat").toBeGreaterThan(0);

    const rendered = new Set(v.caveats.map((c) => c.text));
    for (const c of expected) {
      expect(rendered.has(c), `the verdict dropped a bound its own search produced: "${c}"`).toBe(true);
    }
    /* No caveat may be invented either: every one must come from a flow that was actually traced. */
    for (const c of rendered) expect(expected.has(c)).toBe(true);
  });

  it("counts how many of the searched flows each caveat bounds", () => {
    const v = runIntentSearch(catalog[0]!);
    expect(v.searched).toBeGreaterThan(0);
    for (const c of v.caveats) {
      expect(c.flows).toBeGreaterThan(0);
      expect(c.flows).toBeLessThanOrEqual(v.searched);
    }
    /* Ordered by how much of the space each bounds — the widest bound reads first. */
    const counts = v.caveats.map((c) => c.flows);
    expect([...counts].sort((a, b) => b - a)).toEqual(counts);
  });

  it("renders them in a never-collapsed section with the trace card's own title", () => {
    const v = runIntentSearch(catalog[0]!);
    const { container } = mount(<IntentClaimCard verdict={v} />);
    const said = text(container);
    expect(said).toContain("every reason this result is narrower than it looks");
    for (const c of v.caveats) expect(said).toContain(c.text);
    /* The bound that most often flips a universal claim: the forward direction only. */
    expect(said).toMatch(/only the forward direction/i);
  });
});
