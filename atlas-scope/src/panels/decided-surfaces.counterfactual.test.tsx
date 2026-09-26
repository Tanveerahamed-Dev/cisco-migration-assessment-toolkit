/**
 * decided-surfaces.counterfactual.test.tsx — every surface's DECIDED branch, drawn for a real trace.
 *
 * Why this file exists (2026-09-22 auditor, B1 + B2). The decided traces the panel tests used to
 * render — "a definite delivery is drawn RESOLVED", "a decided denial offers a counterexample", the
 * SVI-sourced intents that reached "no-counterexample-found" — were ALL sourced from core1's own SVI
 * addresses (10.0.30.1, 10.0.20.2). The engine walked a packet the router ORIGINATES as though it
 * arrived inbound on that SVI and applied the SVI's inbound list, which is the defect: it now refuses
 * such a source as router-originated. Every remaining delivery or denial rests on a route chosen from
 * a table the snapshot shows incomplete, so it is not decided either. The shipped snapshot therefore
 * has no decided trace, and the original files pin that.
 *
 * The decided branches are still the code under test, so this file runs the real engine over the
 * real compiled snapshot with two COMPLETENESS producers answered counterfactually: core1's and
 * core2's routing tables treated as complete, and every physical port a source could arrive by
 * treated as observed binding no list. Routes, ACL lines, bindings and FHRP records are unchanged, the
 * sources are ordinary host addresses in 10.0.30.0/24 (one gateway: core1 Vlan30, no FHRP alternate),
 * and vitest isolates modules per file, so the counterfactual never reaches another test or the product.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../forwarding/rib-completeness", async (orig) => {
  const actual = await orig<typeof import("../forwarding/rib-completeness")>();
  return { ...actual, ribIncompleteness: () => [], ribIncompletenessSentence: () => null };
});
vi.mock("../forwarding/bindings", async (orig) => {
  const actual = await orig<typeof import("../forwarding/bindings")>();
  return { ...actual, physicalIngressStates: () => [] };
});

import { bandOfTrace, isDecidedOutcome } from "../core/claims";
import { fabric } from "../core/data";
import type { Flow } from "../core/types";
import { counterexample, isDefiniteDelivery, traceFlow } from "../forwarding/engine";
import { traceMarkOf } from "../fabric3d/Fabric3D";
import { ClaimCard } from "./ClaimCard";
import { HopList } from "./HopList";
import { intentCatalog, runIntentSearch, type Intent } from "./PathTrace";

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

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({ srcIp, dstIp, protocol, dstPort, srcPort: null });
const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ");
const click = (el: Element): void => {
  act(() => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
};

/** A host in 10.0.30.0/24, not a device address: the source every decided case below uses. */
const HOST = "10.0.30.5";
const DELIVERED = flow(HOST, "10.0.10.50", "tcp", 443);
const DENIED = flow(HOST, "10.0.40.5", "tcp", 443);

describe("the counterfactual really does produce decided traces from a HOST source", () => {
  it("delivered is RESOLVED, denied is REFUTED, and neither source is a device's own address", () => {
    const owned = new Set(fabric.l3.flatMap((r) => [r.sviIp?.split(/[ /]/)[0], r.vip]).filter((x): x is string => typeof x === "string"));
    expect(owned.has(HOST), "precondition: the source is not a device address").toBe(false);
    expect(bandOfTrace(traceFlow(DELIVERED))).toBe("RESOLVED");
    expect(bandOfTrace(traceFlow(DENIED))).toBe("REFUTED");
  });
});

describe("ClaimCard + HopList — a definite delivery", () => {
  it("is drawn RESOLVED on the card and on the hop, and its claim carries no undecided suffix", () => {
    const t = traceFlow(DELIVERED);
    expect(isDefiniteDelivery(t)).toBe(true);
    expect(t.claim).not.toMatch(/not a decided pass/);
    const el = mount(
      <>
        <ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />
        <HopList trace={t} activeIndex={null} onSelect={() => {}} />
      </>,
    );
    expect(el.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("RESOLVED");
    expect(el.querySelector<HTMLElement>(".hop .verdict")!.dataset["band"]).toBe("RESOLVED");
  });
});

describe("ClaimCard — a decided denial and its counterexample", () => {
  const t = traceFlow(DENIED);
  const ce = counterexample(t.flow, t);

  it("the denial is decided and a counterexample is found", () => {
    expect(t.outcome).toBe("denied");
    expect(isDecidedOutcome(t)).toBe(true);
    expect(ce.found).toBe(true);
  });

  it("is headed 'Counterexample' with a decided counter outcome wearing its own band", () => {
    if (!ce.found) throw new Error("precondition failed: no counterexample");
    expect(isDecidedOutcome(ce.trace)).toBe(true);
    const el = mount(<ClaimCard trace={t} counterexample={ce} />);
    expect(text(el)).toMatch(/Counterexample — the nearest flow that behaves differently/);
    expect(text(el)).not.toMatch(/so not a counterexample/);
    const outcome = el.querySelector<HTMLElement>(".claim__counter-outcome");
    expect(outcome?.dataset.band).toBe(bandOfTrace(ce.trace));
    expect(outcome?.dataset.band).not.toBe("UNDETERMINED");
  });

  it("names what the counterexample changed instead of claiming the same addresses", () => {
    if (!ce.found) throw new Error("precondition failed: no counterexample");
    const el = mount(<ClaimCard trace={t} counterexample={ce} />);
    const pair = text(el.querySelector(".claim__pair"));
    expect(pair).toMatch(/its (source|destination|protocol|destination port) \(/);
    expect(pair).not.toMatch(/between the same addresses/);
  });

  it("offers the counterexample and can run it, with the two-part 'Not established' contract", () => {
    if (!ce.found) throw new Error("precondition failed: no counterexample");
    const ran: Flow[] = [];
    const el = mount(<ClaimCard trace={t} counterexample={ce} onRunFlow={(f) => ran.push(f)} />);
    const btn = [...el.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes("Trace this flow instead"));
    expect(btn).toBeDefined();
    click(btn!);
    expect(ran.length).toBe(1);
    expect(JSON.stringify(ran[0])).not.toBe(JSON.stringify(t.flow));
    expect(text(el)).toContain("Not established");
  });

  it("keeps the counterexample affordance when there is nothing to offer, carrying the reason", () => {
    const el = mount(<ClaimCard trace={t} counterexample={{ found: false, reason: "None of the 3 nearby variations traced as delivered." }} />);
    expect(text(el)).toContain("None of the 3 nearby variations");
    expect(text(el)).toContain("Counterexample");
  });
});

describe("the 3-D trace mark never claims more than the trace band", () => {
  it("over decided and undecided real traces, each branch counted", () => {
    const flows = [DELIVERED, DENIED, flow("10.0.10.50", "10.0.30.10", "icmp", null), flow("10.0.40.50", "10.0.30.10", "tcp", 443)];
    const ran = { delivered: 0, blocked: 0, undetermined: 0 };
    for (const f of flows) {
      const t = traceFlow(f);
      const mark = traceMarkOf(t);
      const band = bandOfTrace(t);
      if (mark === null) continue;
      ran[mark.kind] += 1;
      if (mark.kind === "delivered") expect(band).toBe("RESOLVED");
      if (mark.kind === "blocked") expect(band).toBe("REFUTED");
      if (band === "UNDETERMINED") expect(mark.kind).toBe("undetermined");
    }
    expect(ran.delivered).toBeGreaterThan(0);
    expect(ran.blocked).toBeGreaterThan(0);
    expect(ran.undetermined).toBeGreaterThan(0);
  });
});

describe("runIntentSearch — decided verdicts from a host source", () => {
  const catalog = intentCatalog();
  const hostIntents = (): { refuted: Intent; held: Intent; mixed: Intent } => {
    const l3 = fabric.l3.find((r) => r.host === "core1" && r.vlan === 30);
    if (l3 === undefined) throw new Error("the snapshot no longer records core1's Vlan30 SVI");
    const src = { ip: HOST, provenance: "derived" as const, cite: l3.cite, note: "a host address inside core1's Vlan30 subnet" };
    const v20 = catalog.find((i) => i.id === "no-reach-10_0_20_0_24-10_0_30_0_24")!;
    const v10 = catalog.find((i) => i.id === "no-reach-10_0_10_0_24-10_0_30_0_24")!;
    const from = (base: Intent, kind: Intent["kind"], id: string, claim: string): Intent => ({
      ...base,
      id,
      kind,
      claim,
      sources: [src],
      destinations: base.sources,
      sourceSpace: base.destSpace,
      destSpace: base.sourceSpace,
    });
    return {
      refuted: from(v20, "none-reach", "host-none-reach-vlan20", "No flow from 10.0.30.5 reaches 10.0.20.0/24."),
      held: from(v20, "all-reach", "host-all-reach-vlan20", "Every flow from 10.0.30.5 reaches 10.0.20.0/24."),
      mixed: from(v10, "all-reach", "host-all-reach-vlan10", "Every flow from 10.0.30.5 reaches 10.0.10.0/24."),
    };
  };

  it("never offers a counterexample the engine itself says it cannot decide", () => {
    const counted = { all: 0, delivered: 0 };
    for (const i of [...catalog, hostIntents().refuted]) {
      const v = runIntentSearch(i);
      for (const c of v.counterexamples) {
        counted.all += 1;
        expect(c.trace.caveats.some((x) => /never a definite permit/.test(x)), JSON.stringify(c.flow)).toBe(false);
        if (c.trace.outcome === "delivered") {
          counted.delivered += 1;
          expect(isDefiniteDelivery(c.trace)).toBe(true);
        }
      }
    }
    expect(counted.all, "no counterexample was examined").toBeGreaterThan(0);
    expect(counted.delivered, "no delivered counterexample was examined").toBeGreaterThan(0);
  });

  it("never counts an undecided flow as consistent with the intent", () => {
    const h = hostIntents();
    const ran = { clean: 0, passesBesideUndecided: 0 };
    for (const i of [...catalog, h.held, h.mixed]) {
      const v = runIntentSearch(i);
      expect(v.satisfying + v.counterexamples.length + v.undecided).toBe(v.searched);
      if (v.outcome === "no-counterexample-found") {
        ran.clean += 1;
        expect(v.undecided, i.id).toBe(0);
      }
      if (v.satisfying > 0 && v.undecided > 0) {
        ran.passesBesideUndecided += 1;
        expect(v.outcome, i.id).not.toBe("no-counterexample-found");
      }
    }
    expect(ran.clean).toBeGreaterThan(0);
    expect(ran.passesBesideUndecided).toBeGreaterThan(0);
  });
});
