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
import { counterexample, isDefiniteDelivery, traceFlow } from "../forwarding/engine";
import { formatPrefix, parseInterfaceAddress, parseIpv4, prefixContains } from "../forwarding/ip";
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
const DROPPED_OFF_FABRIC = flow("10.0.20.50", "198.51.100.7", "tcp", 443);

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
    // 1-based with the list length; the 0-based index survives only in the citation (A3).
    expect(body).toContain("PROTECT_SERVERS line 4 of 4");
    expect(body).toContain("acls.core1.PROTECT_SERVERS[3]");
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

/* ══ A2: a MODEL gap is never reported as a COLLECTION gap ═════════════════ */

describe("HopList — an undecided hop on a host whose RIB WAS collected", () => {
  /* The critic's real flow. core1 has a collected RIB; the route (0.0.0.0/0 via 10.0.10.254) was
     decided, and the hop is undecided only because INET_RETURN line 0 ("established") cannot be
     evaluated. It used to read "not modelled — nothing was collected here to decide an egress
     from", with no EGRESS row, beside the very route that was decided. */
  const INTERNET = flow("10.0.10.50", "8.8.8.8", "tcp", 443);
  const trace = traceFlow(INTERNET);

  it("rests on the data it claims to", () => {
    const hop = trace.hops[0]!;
    expect(hop.host).toBe("core1");
    expect(hop.verdict).toBe("unmodeled");
    expect(hop.nextHop).toBe("10.0.10.254");
    expect(hop.decidedBy?.cite).toBe("acls.core1.INET_RETURN[0]");
  });

  it("renders EGRESS and NEXT from the matched route and names the unevaluable ACL line", () => {
    const { container } = mount(<HopList trace={trace} activeIndex={0} onSelect={() => {}} />);
    const facts = [...container.querySelectorAll(".hop__fact")].map((f) => text(f));
    const body = text(container);
    expect(body).not.toContain("nothing was collected");
    expect(facts.some((f) => /^Egress/.test(f))).toBe(true);
    expect(facts.find((f) => /^Next/.test(f)) ?? "").toContain("10.0.10.254");
    expect(body).toContain("ACL INET_RETURN line 1 of 3 on core1 cannot be evaluated for this flow");
    // A2: the static default names only a next hop; the egress is resolved through the RIB and cited.
    expect(facts.find((f) => /^Egress/.test(f)) ?? "").toMatch(
      /Vlan10.*resolved: next hop 10\.0\.10\.254 lies in connected 10\.0\.10\.0\/24.*routes\.core1\[2\]/,
    );
    expect(container.querySelector(".verdict__word")?.textContent).toBe("undecided");
    // Still UNDETERMINED: the new wording is not a softer verdict.
    expect(container.querySelector(".hop")?.getAttribute("data-band")).toBe("UNDETERMINED");
  });

  it("does the same for the connected-route case, with no next hop invented", () => {
    const icmp = traceFlow(INDETERMINATE);
    const { container } = mount(<HopList trace={icmp} activeIndex={0} onSelect={() => {}} />);
    const facts = [...container.querySelectorAll(".hop__fact")].map((f) => text(f));
    expect(text(container)).not.toContain("nothing was collected");
    expect(facts.find((f) => /^Egress/.test(f)) ?? "").toContain("Vlan30");
    expect(facts.find((f) => /^Next/.test(f)) ?? "").toContain("directly connected");
  });

  it("keeps the collection-gap wording for a host with NO RIB, and claims no routes were beaten there", () => {
    const { container } = mount(<HopList trace={traceFlow(UNMODELLED)} activeIndex={0} onSelect={() => {}} />);
    const noRib = [...container.querySelectorAll(".hop")].find((h) => h.getAttribute("data-verdict") === "unmodeled")!;
    expect(text(noRib)).toContain("no routing table was collected");
    expect(text(noRib)).not.toContain("nothing was beaten");
    expect(noRib.querySelector(".hop__why-none")).toBeNull();
  });
});

/* ══ A3: the reader lands ON the answer ═════════════════════════════════════ */

describe("PathTrace — a new result is scrolled into view", () => {
  it("scrolls its own scroller to the blocking hop after a trace runs", async () => {
    /* jsdom has no layout, so the geometry is stubbed: the scroller is the panel, and every
       element reports a top of 3000 px except the scroller itself. What is asserted is that the
       panel MOVED its own scroller to the blocking hop card — not the page. */
    const rect = HTMLElement.prototype.getBoundingClientRect;
    const hopTop = 3000;
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
      const top = this.classList.contains("pt-panel") ? 100 : this.classList.contains("hop") ? hopTop : 500;
      return { top, bottom: top + 10, left: 0, right: 10, width: 10, height: 10, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
    };
    const sh = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    const ch = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 5000 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 400 });
    const style = document.createElement("style");
    style.textContent = ".pt-panel { overflow-y: auto; }";
    document.head.appendChild(style);
    try {
      const { container } = mount(<PathTrace />);
      const panel = container.querySelector<HTMLElement>(".pt-panel")!;
      expect(panel.scrollTop).toBe(0);
      act(() => useInvestigation.getState().setFlow(DENIED));
      const hop = container.querySelector('.hop[data-verdict="denied"]');
      expect(hop).not.toBeNull();
      /* A result that ARRIVED (here: a store write, as a restored link makes) lands after the next
         paint, not in the pre-paint task that mounted it — acceptance E5, see PathTrace.tsx. The
         panel's own answer is already drawn; the scroll follows one frame later. */
      expect(panel.scrollTop).toBe(0);
      await settleCommit();
      expect(panel.scrollTop).toBe(hopTop - 100 - 8);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = rect;
      if (sh) Object.defineProperty(HTMLElement.prototype, "scrollHeight", sh);
      if (ch) Object.defineProperty(HTMLElement.prototype, "clientHeight", ch);
      style.remove();
    }
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

  it("offers no counterexample against a router-originated flow, and none for the core2 drop", () => {
    /* REVERSED 2026-09-22 (auditor, B2). This test ran the affordance on tcp 10.0.20.2 -> 10.0.10.50:22,
       a "decided" denial that existed only because the engine applied core1 Vlan20's INBOUND list to
       a packet core1 itself originates. That flow is now refused, so nothing is offered against it.
       The affordance itself ("Trace this flow instead", "Not established", the reason carried when
       nothing is found) is exercised on a decided host-sourced denial in decided-surfaces.counterfactual.test.tsx. */
    const trace = traceFlow(flow("10.0.20.2", "10.0.10.50", "tcp", 22));
    expect(trace.hops).toEqual([]);
    const ce = counterexample(trace.flow, trace);
    expect(ce.found).toBe(false);
    const { container } = mount(<ClaimCard trace={trace} counterexample={ce} onRunFlow={() => {}} />);
    expect([...container.querySelectorAll("button")].some((b) => (b.textContent ?? "").includes("Trace this flow instead"))).toBe(false);
    expect(container.querySelector(".claim")?.getAttribute("data-band")).toBe("UNDETERMINED");
    // And the core2 drop is never answered with a core2 delivery: core2 has no collected ACL.
    const off = traceFlow(DROPPED_OFF_FABRIC);
    const offCe = counterexample(off.flow, off);
    expect(offCe.found).toBe(false);
    if (!offCe.found) expect(offCe.reason).toMatch(/nearby variations derived from the evidence at core2/);
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

/* C2 (acceptance, 2026-09-22): both address fields showed the same placeholder, "10.0.10.50", so the
   empty form suggested a flow from a host to itself — the one example that can never be the question
   a reader is asking. Each field's example must be its own address, and each must be one this
   snapshot can answer questions about: inside a subnet the collection actually observed on an L3
   interface. The subnets are re-derived here from the compiled records, not read back from the
   component, so a component that invents an address cannot also invent the subnet that excuses it. */
describe("PathTrace — the flow form's example addresses", () => {
  const observedSubnets = fabric.l3.flatMap((r) => {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    return a === null ? [] : [a.prefix];
  });
  const routerAddresses = new Set(
    fabric.l3.flatMap((r) => {
      const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
      const vip = r.vip === null ? null : parseIpv4(r.vip);
      return [a?.ip ?? null, vip].filter((x): x is NonNullable<typeof x> => x !== null);
    }),
  );
  const subnetOf = (ip: string): string | null => {
    const v = parseIpv4(ip);
    if (v === null) return null;
    const p = observedSubnets.find((s) => prefixContains(s, v));
    return p === undefined ? null : formatPrefix(p);
  };
  const placeholders = (): { src: string; dst: string } => {
    const { container } = mount(<PathTrace />);
    const byLabel = (name: string): HTMLInputElement => {
      const label = [...container.querySelectorAll("label")].find((l) => text(l).trim().startsWith(name));
      const input = label ? document.getElementById(label.htmlFor) : null;
      if (!(input instanceof HTMLInputElement)) throw new Error(`no input is labelled "${name}"`);
      return input;
    };
    return { src: byLabel("Source IP").placeholder, dst: byLabel("Destination IP").placeholder };
  };

  it("rests on a snapshot that observed more than one subnet", () => {
    expect(new Set(observedSubnets.map(formatPrefix)).size).toBeGreaterThan(1);
  });

  it("shows a different example in the Source IP and Destination IP fields", () => {
    const { src, dst } = placeholders();
    expect(src).not.toBe("");
    expect(dst).not.toBe("");
    expect(src).not.toBe(dst);
  });

  it("draws each example from a subnet the collection observed, never a router's own address", () => {
    const { src, dst } = placeholders();
    for (const ip of [src, dst]) {
      expect(subnetOf(ip), `${ip} lies in no observed subnet`).not.toBeNull();
      expect(routerAddresses.has(parseIpv4(ip)!), `${ip} is a gateway address, not a client`).toBe(false);
    }
    // Two subnets were observed, so the example flow crosses between them rather than staying in one.
    expect(subnetOf(src)).not.toBe(subnetOf(dst));
  });

  it("names the field's own example in that field's validation message", () => {
    const { src, dst } = placeholders();
    const r = validateFlowForm({ srcIp: "", dstIp: "10.0.30.0/24", protocol: "tcp", dstPort: "" });
    expect(r.errors.srcIp).toContain(src);
    expect(r.errors.dstIp).toContain(dst);
    expect(r.errors.srcIp).not.toContain(dst);
    expect(r.errors.dstIp).not.toContain(src);
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

  it("traces the flow the store carries, so a shared link reproduces the result", async () => {
    const { container } = mount(<PathTrace />);
    act(() => useInvestigation.getState().setFlow(DENIED));
    /* The panel answers from local state at once; the store write that re-aims the other surfaces
       lands after the next paint (acceptance E5 — a cold restore used to do it before the first). */
    expect(text(container)).toContain("PROTECT_SERVERS");
    expect(useInvestigation.getState().trace).toBeNull();
    await settleCommit();
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
  it("states no routing counterfactual it never evaluated, and names the ingress it assumed", () => {
    /* Critic B2, 2026-09-21: "a route added later would end this result without any change to an
       ACL" was false — under the alternate FHRP ingress (core1) the same flows are all DENIED. */
    const verdicts = catalog.map((i) => runIntentSearch(i));
    /* UPDATED 2026-09-21 (critic B1 blocker). The only shipped intent whose consistent flows all
       "stopped for want of a route" was VLAN 20 → 10.0.30.0/24, and every one of those 60 drops sat on
       core2's collected table — which the snapshot itself shows to be incomplete (OSPF/BGP/EIGRP
       not_collected, a 240-prefix EVPN peer). Those drops are now UNDECIDED, so no shipped verdict
       reaches the "for want of a route" collateral and the rule below is asserted wherever it fires.
       What must hold instead on the real data: the drops are counted undecided, for that reason. */
    const vlan20 = verdicts.find((v) => v.intent.id === "no-reach-10_0_20_0_24-10_0_30_0_24")!;
    expect(vlan20.outcome).not.toBe("no-counterexample-found");
    expect(vlan20.undecided).toBe(vlan20.searched);
    expect(vlan20.undecidedReasons.some((r) => /collected routing table is itself incomplete/.test(r.reason))).toBe(true);
    for (const v of verdicts) {
      for (const c of v.collateral) {
        expect(c).not.toMatch(/would end this result|would survive a routing change/);
        if (/for want of a route/.test(c)) expect(c).toMatch(/as ingress — chosen from point-in-time FHRP\/SVI evidence/);
      }
    }
  });

  it("THE regression: a result with no counterexample always carries the unmodelled-hosts sentence", () => {
    const withoutRib = fabric.devices.length - fabric.coverage.hostsWithRoutes;
    expect(withoutRib).toBeGreaterThan(0);

    /* UPDATED 2026-09-21 (critic B1 blocker): the one "clean" verdict the shipped data produced was a
       false proof over core2's incomplete routing table, and is now undecided — so no shipped intent
       returns no-counterexample-found. The sentence is mandatory for EVERY outcome (see
       finishIntentSearch), so it is asserted on every verdict: a stronger test than the clean subset,
       and one the real data exercises. */
    const all = catalog.map((i) => runIntentSearch(i));
    expect(all.length).toBeGreaterThan(0);

    for (const v of all) {
      expect(v.unmodelledSentence).not.toBeNull();
      expect(v.unmodelledSentence).toContain(String(withoutRib));
      expect(v.unmodelledSentence).toContain("could violate this intent");
      // And the bound sentence names the space it searched, not just the absence of a hit.
      expect(v.boundSentence).toContain(String(v.searched));
      expect(v.boundSentence).toContain(fabric.coverage.routableHosts[0]!);
    }
  });

  it("renders that sentence, not just computes it", () => {
    // Any verdict: the sentence is unconditional (see the test above for why no shipped one is clean).
    const verdict = runIntentSearch(catalog.find((i) => i.id === "no-reach-10_0_20_0_24-10_0_30_0_24")!);
    const { container } = mount(<IntentClaimCard verdict={verdict} />);
    const body = text(container);
    expect(body).not.toContain("No counterexample was found");
    expect(body).toContain("could not be decided");
    expect(body).toContain("could violate this intent");
    // The sentence is not tucked inside a collapsed region.
    const el = [...container.querySelectorAll("p")].find((p) =>
      (p.textContent ?? "").includes("could violate this intent"),
    );
    expect(el?.closest("[hidden]")).toBeNull();
  });

  /* Since 2026-09-21 no SHIPPED intent has a decided counterexample: every contradiction the catalog
     used to report rested on a denial by a list whose `ip access-group` binding was never collected
     (see contradicts()). So the affordance is exercised on a real catalog intent with its polarity
     flipped: "no flow from VLAN 20 reaches 10.0.30.0/24" holds because core2 has no route, and
     "every flow does" is contradicted by exactly those drops — decided, cited, real engine output. */
  const flipped = (): Intent => {
    const base = catalog.find((i) => i.id === "no-reach-10_0_20_0_24-10_0_30_0_24")!;
    return { ...base, id: `${base.id}-flipped`, kind: "all-reach", claim: "Every flow from VLAN 20 reaches 10.0.30.0/24." };
  };

  /* REAL intents that reach the two verdicts the shipped catalogue no longer reaches (critic F2,
     2026-09-22: the counterexample loop below ran 0 times, and the "no-counterexample-found" guard
     ran only where it was inert). Their source is core1's own Vlan30 SVI address, read from the
     snapshot's l3_forwarding record — not a fabricated trace. From there the engine returns DECIDED
     deliveries to VLAN 20 (the connected-route path has no undecided input), so:
       - "no flow from the SVI reaches VLAN 20" is refuted by decided counterexamples;
       - "every flow from the SVI reaches VLAN 20" holds with nothing undecided;
       - "every flow from the SVI reaches VLAN 10" has decided passes AND undecided flows — the case
         the undecided-is-not-consistent rule actually bites on. */
  const sviIntents = (): { refuted: Intent; held: Intent; mixed: Intent } => {
    const l3 = fabric.l3.find((r) => r.host === "core1" && r.sviIp?.split(" ")[0] === "10.0.30.1");
    if (l3 === undefined) throw new Error("the snapshot no longer records core1's Vlan30 SVI at 10.0.30.1");
    const svi = { ip: "10.0.30.1", provenance: "observed" as const, cite: l3.cite, note: "core1's own Vlan30 SVI address" };
    const v20 = catalog.find((i) => i.id === "no-reach-10_0_20_0_24-10_0_30_0_24")!;
    const v10 = catalog.find((i) => i.id === "no-reach-10_0_10_0_24-10_0_30_0_24")!;
    const from = (base: Intent, kind: Intent["kind"], id: string, claim: string): Intent => ({
      ...base,
      id,
      kind,
      claim,
      sources: [svi],
      destinations: base.sources,
      sourceSpace: base.destSpace,
      destSpace: base.sourceSpace,
    });
    return {
      refuted: from(v20, "none-reach", "svi-none-reach-vlan20", "No flow from core1's Vlan30 SVI reaches 10.0.20.0/24."),
      held: from(v20, "all-reach", "svi-all-reach-vlan20", "Every flow from core1's Vlan30 SVI reaches 10.0.20.0/24."),
      mixed: from(v10, "all-reach", "svi-all-reach-vlan10", "Every flow from core1's Vlan30 SVI reaches 10.0.10.0/24."),
    };
  };

  it("counts no heuristic-list denial as a decided contradiction", () => {
    /* REGRESSION: reach-gateway-10_0_10_0_24 reported COUNTEREXAMPLE FOUND with 12 decided
       contradictions, all resting on acls.core1.INET_RETURN[2] — a list chosen by the specificity
       rule, with no collected binding, whose line the scope block listed as undecidable. */
    const v = runIntentSearch(catalog.find((i) => i.id === "reach-gateway-10_0_10_0_24")!);
    expect(v.outcome).not.toBe("counterexample-found");
    expect(v.decidedReasons.filter((r) => r.cite.startsWith("acls."))).toEqual([]);
    expect(v.undecided).toBeGreaterThan(0);
  });

  it("finds a counterexample where one exists and makes it runnable", () => {
    /* UPDATED 2026-09-21 (critic B1 blocker). The flipped intent's "decided" contradictions were the
       core2 no-route drops, which rest on a routing table the snapshot shows to be incomplete; they
       are now undecided, and no shipped or flipped intent has a DECIDED counterexample. The engine
       side of that is pinned in "never offers a counterexample the engine itself says it cannot
       decide" below. This test is about the AFFORDANCE, so when the data offers no decided
       counterexample it is exercised on a real verdict carrying a real engine trace — stated, not
       hidden. */
    const verdicts = [...catalog, flipped()].map((i) => runIntentSearch(i));
    const base = verdicts.find((v) => v.outcome === "counterexample-found") ?? verdicts[0]!;
    const real = traceFlow({ srcIp: "10.0.20.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 443, srcPort: null });
    const found =
      base.outcome === "counterexample-found"
        ? base
        : { ...base, outcome: "counterexample-found" as const, counterexamples: [{ flow: real.flow, trace: real }] };
    const first = found.counterexamples[0]!;
    expect(traceFlow(first.flow).outcome).toBe(first.trace.outcome);

    const ran: Flow[] = [];
    const { container } = mount(<IntentClaimCard verdict={found!} onRunFlow={(f) => ran.push(f)} />);
    const btn = [...container.querySelectorAll("button")].find((b) =>
      (b.textContent ?? "").includes("Open this flow in the trace view"),
    );
    click(btn!);
    expect(ran[0]).toEqual(first.flow);
  });

  it("never offers a counterexample the engine itself says it cannot decide", () => {
    /* REGRESSION. "No flow from VLAN 10 reaches 10.0.30.0/24" used to report counterexample-found
       with 24 counterexamples, all 24 of them deliveries whose own caveat read "at best
       indeterminate, never a definite permit" — a refutation built on undecided evidence.
       UPDATED 2026-09-22 (auditor, B1 + B2): on this snapshot NO intent has a counterexample — the
       SVI intents that supplied decided ones were sourced by core1's own address. The loop still
       checks whatever is offered; the non-vacuous run with decided counterexamples is in decided-surfaces.counterfactual.test.tsx. */
    for (const i of [...catalog, flipped(), sviIntents().refuted]) {
      const v = runIntentSearch(i);
      for (const c of v.counterexamples) {
        expect(c.trace.caveats.some((x) => /never a definite permit/.test(x)), JSON.stringify(c.flow)).toBe(false);
        if (c.trace.outcome === "delivered") expect(isDefiniteDelivery(c.trace)).toBe(true);
      }
    }
    const vlan10 = runIntentSearch(catalog[0]!);
    expect(vlan10.counterexamples.filter((c) => c.trace.outcome === "delivered")).toEqual([]);
    // Every undecided row says why — none is a bare "core1 permits/denies".
    for (const r of vlan10.undecidedReasons) expect(r.reason, r.cite).toMatch(/— but |not decided|refused|not modelled|itself/);
  });

  it("an intent sourced by a router's own address is never decided (the auditor's crafted intent)", () => {
    /* 2026-09-22 auditor (B2): none-reach from 10.0.20.2 (core1's Vlan20 address) to 10.0.10.50 over
       udp/53 + tcp/443 returned "no-counterexample-found" with "2 of 2 decided: 2 denied (decided)" —
       both denials were core1 Vlan20's INBOUND list applied to traffic core1 itself originates. */
    const l3 = fabric.l3.find((r) => r.host === "core1" && r.sviIp?.split(" ")[0] === "10.0.20.2");
    if (l3 === undefined) throw new Error("the snapshot no longer records core1's Vlan20 SVI at 10.0.20.2");
    const base = catalog.find((i) => i.kind === "none-reach")!;
    const crafted: Intent = {
      ...base,
      id: "auditor-crafted-none-reach",
      claim: "No flow from 10.0.20.2 reaches 10.0.10.50.",
      sources: [{ ip: "10.0.20.2", provenance: "observed", cite: l3.cite, note: "core1's own Vlan20 address" }],
      destinations: [{ ip: "10.0.10.50", provenance: "derived", cite: l3.cite, note: "a host in VLAN 10" }],
      services: [
        { protocol: "udp", dstPort: 53, label: "udp/53", cite: l3.cite },
        { protocol: "tcp", dstPort: 443, label: "tcp/443", cite: l3.cite },
      ],
    };
    const v = runIntentSearch(crafted);
    expect(v.searched).toBe(2);
    expect(v.outcome).not.toBe("no-counterexample-found");
    expect(v.counterexamples).toEqual([]);
    expect(v.undecided).toBe(v.searched);
    for (const i of Object.values(sviIntents())) {
      const r = runIntentSearch(i);
      expect(r.outcome, i.id).toBe("indeterminate");
      expect(r.undecided, i.id).toBe(r.searched);
    }
  });

  it("never counts an undecided flow as consistent with the intent", () => {
    /* Each guard that CAN run on this snapshot is counted and required to have run. The clean
       ("no-counterexample-found") and passes-beside-undecided branches ran only on the SVI intents,
       which were router-originated (auditor, B2, 2026-09-22); they run on a host source in decided-surfaces.counterfactual.test.tsx. */
    const ran = { undecidedNoCounter: 0 };
    for (const i of [...catalog, ...Object.values(sviIntents())]) {
      const v = runIntentSearch(i);
      expect(v.satisfying + v.counterexamples.length + v.undecided).toBe(v.searched);
      if (v.undecided > 0 && v.counterexamples.length === 0) {
        ran.undecidedNoCounter += 1;
        expect(v.outcome, i.id).toBe("indeterminate");
      }
      if (v.outcome === "no-counterexample-found") expect(v.undecided, i.id).toBe(0);
      if (v.satisfying > 0 && v.undecided > 0) expect(v.outcome, i.id).not.toBe("no-counterexample-found");
    }
    expect(ran.undecidedNoCounter).toBeGreaterThan(0);
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
  it("selects the hop's own host, so the device pane and evidence rail follow it", async () => {
    /* The store's `selectHop` writes `hopIndex` and nothing else. A4 names the hop as one of the
       four selections that must re-aim the others, and it did not: with device access13 selected
       and the denied trace open, clicking "Hop 1 of 1: core1 denied" left the device pane showing
       access13 ("Routing: no RIB collected") — the hop click led nowhere.
       Driven through the real component and the real engine: the assertion is on the STORE, which
       is what the device pane, the evidence rail and the fabric all read. */
    const { container } = mount(<PathTrace />);
    act(() => useInvestigation.getState().setFlow(DENIED));
    await settleCommit(); // the restored trace reaches the store after the next paint (E5)

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
