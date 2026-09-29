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
 *
 * RE-EXPRESSED 2026-09-28 (phase 3). The premise above — "the shipped snapshot has no decided trace" —
 * is no longer true: the regenerated sample has decided multi-hop traces, drawn on the REAL data in
 * PathTrace.decided-multihop.test.tsx. This file stays, because the counterfactual still reaches decided
 * branches the real data does not (a decided delivery from a single-gateway subnet's host, SCOPED at its
 * ceiling). But its subjects were named flows, and the regenerated routes changed their outcomes (the
 * "denied" flow 10.0.30.5 -> 10.0.40.5:443 is now DELIVERED over core1 to dist1). So the subjects are now
 * found by property under the counterfactual: the source is an ordinary host address in a subnet with
 * exactly one gateway, the delivery is the first definite one from it, and the denial is the first
 * decided one — from any host source — with a decided counterexample.
 *
 * Every subject is resolved INSIDE its test through `need` (trace-universe.ts): on a snapshot that is not
 * the reference sample an absent subject is a skip that names what the snapshot lacks, and on the reference
 * sample it is a failure. Nothing is resolved at collection, so no snapshot can crash the file there. The
 * universe includes a host inside every routed off-SVI prefix, which is where the engine's golden fleet's
 * only decided denial goes (10.0.30.x -> 10.0.0.0/16) — an SVI-only universe missed it (verifier V1).
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi, type TestContext } from "vitest";

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
import type { Flow, Trace } from "../core/types";
import { counterexample, isDefiniteDelivery, traceFlow } from "../forwarding/engine";
import { traceMarkOf } from "../fabric3d/Fabric3D";
import { ClaimCard } from "./ClaimCard";
import { HopList } from "./HopList";
import { intentCatalog, runIntentSearch, type Intent } from "./PathTrace";
import { deviceOwnedAddresses, need, subnetHostAddresses, universeTraces } from "./trace-universe";

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

const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ");
const click = (el: Element): void => {
  act(() => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
};

/** An ordinary host address in a subnet exactly ONE gateway serves (no FHRP alternate), with its SVI record. */
const singleGatewayHost = (): ReturnType<typeof subnetHostAddresses>[number] | undefined => {
  const gateways = new Map<string, number>();
  for (const r of fabric.l3) if (r.primarySubnet !== null) gateways.set(r.primarySubnet, (gateways.get(r.primarySubnet) ?? 0) + 1);
  return subnetHostAddresses().find((h) => {
    const rec = fabric.l3.find((r) => r.cite === h.cite);
    return rec?.primarySubnet != null && gateways.get(rec.primarySubnet) === 1;
  });
};
const hostSource = (ctx: TestContext): string => need(ctx, singleGatewayHost(), "host address in a subnet with exactly one gateway").ip;
const deliveredFrom = (src: string): Trace | undefined => universeTraces().find((t) => t.flow.srcIp === src && isDefiniteDelivery(t));
const decidedDenialWithCounter = (): Trace | undefined =>
  universeTraces().find((t) => {
    if (t.outcome !== "denied" || !isDecidedOutcome(t)) return false;
    const ce = counterexample(t.flow, t);
    return ce.found && isDecidedOutcome(ce.trace);
  });
const owned = (): Set<string> => deviceOwnedAddresses();
/** The decided denial and its decided counterexample, resolved inside the test that needs them. */
const denialSubject = (ctx: TestContext): { t: Trace; ce: Extract<ReturnType<typeof counterexample>, { found: true }> } => {
  const t = need(ctx, decidedDenialWithCounter(), "decided denial with a decided counterexample");
  const ce = counterexample(t.flow, t);
  if (!ce.found) throw new Error("unreachable: decidedDenialWithCounter found a counterexample");
  return { t, ce };
};

describe("the counterfactual really does produce decided traces from a HOST source", () => {
  it("delivered is RESOLVED, denied is REFUTED, and neither source is a device's own address", (ctx) => {
    const src = hostSource(ctx);
    expect(owned().has(src), "precondition: the source is not a device address").toBe(false);
    const delivered = need(ctx, deliveredFrom(src), `definite delivery from ${src}`);
    expect(bandOfTrace(delivered)).toBe("RESOLVED");
    const { t: denied } = denialSubject(ctx);
    expect(owned().has(denied.flow.srcIp), "precondition: the denial's source is not a device address").toBe(false);
    expect(bandOfTrace(denied)).toBe("REFUTED");
  });
});

describe("ClaimCard + HopList — a definite delivery", () => {
  it("is drawn RESOLVED on the card and on the hop, and its claim carries no undecided suffix", (ctx) => {
    const t = need(ctx, deliveredFrom(hostSource(ctx)), "definite delivery from a single-gateway host");
    expect(isDefiniteDelivery(t)).toBe(true);
    expect(t.claim).not.toMatch(/not a decided pass/);
    const el = mount(
      <>
        <ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />
        <HopList trace={t} activeIndex={null} onSelect={() => {}} />
      </>,
    );
    expect(el.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("RESOLVED");
    const verdicts = [...el.querySelectorAll<HTMLElement>(".hop .verdict")];
    expect(verdicts.length, "every hop draws a verdict").toBe(t.hops.length);
    for (const v of verdicts) expect(v.dataset["band"]).toBe("RESOLVED");
  });
});

describe("ClaimCard — a decided denial and its counterexample", () => {
  it("the denial is decided and a counterexample is found", (ctx) => {
    const { t, ce } = denialSubject(ctx);
    expect(t.outcome).toBe("denied");
    expect(isDecidedOutcome(t)).toBe(true);
    expect(ce.found).toBe(true);
  });

  it("is headed 'Counterexample' with a decided counter outcome wearing its own band", (ctx) => {
    const { t, ce } = denialSubject(ctx);
    expect(isDecidedOutcome(ce.trace)).toBe(true);
    const el = mount(<ClaimCard trace={t} counterexample={ce} />);
    expect(text(el)).toMatch(/Counterexample — the nearest flow that behaves differently/);
    expect(text(el)).not.toMatch(/so not a counterexample/);
    const outcome = el.querySelector<HTMLElement>(".claim__counter-outcome");
    expect(outcome?.dataset.band).toBe(bandOfTrace(ce.trace));
    expect(outcome?.dataset.band).not.toBe("UNDETERMINED");
  });

  it("names what the counterexample changed instead of claiming the same addresses", (ctx) => {
    const { t, ce } = denialSubject(ctx);
    const el = mount(<ClaimCard trace={t} counterexample={ce} />);
    const pair = text(el.querySelector(".claim__pair"));
    expect(pair).toMatch(/its (source|destination|protocol|destination port) \(/);
    expect(pair).not.toMatch(/between the same addresses/);
  });

  it("offers the counterexample and can run it, with the two-part 'Not established' contract", (ctx) => {
    const { t, ce } = denialSubject(ctx);
    const ran: Flow[] = [];
    const el = mount(<ClaimCard trace={t} counterexample={ce} onRunFlow={(f) => ran.push(f)} />);
    const btn = [...el.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes("Trace this flow instead"));
    expect(btn).toBeDefined();
    click(btn!);
    expect(ran.length).toBe(1);
    expect(JSON.stringify(ran[0])).not.toBe(JSON.stringify(t.flow));
    expect(text(el)).toContain("Not established");
  });

  it("keeps the counterexample affordance when there is nothing to offer, carrying the reason", (ctx) => {
    const { t } = denialSubject(ctx);
    const el = mount(<ClaimCard trace={t} counterexample={{ found: false, reason: "None of the 3 nearby variations traced as delivered." }} />);
    expect(text(el)).toContain("None of the 3 nearby variations");
    expect(text(el)).toContain("Counterexample");
  });
});

describe("the 3-D trace mark never claims more than the trace band", () => {
  it("over decided and undecided real traces, each branch counted", (ctx) => {
    const delivered = need(ctx, deliveredFrom(hostSource(ctx)), "definite delivery from a single-gateway host");
    const { t: denied } = denialSubject(ctx);
    /* The undecided subjects are found by property too: every trace the counterfactual still leaves
       UNDETERMINED is drawn, not two named flows whose band a regenerated snapshot is free to change. */
    const undecided = universeTraces().filter((t) => bandOfTrace(t) === "UNDETERMINED");
    need(ctx, undecided[0], "trace the counterfactual leaves undecided");
    const flows = [delivered.flow, denied.flow, ...undecided.map((t) => t.flow)];
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
  /* The host-source intents, found by PROPERTY (phase 3.5, P3B-R2-m2). They were two catalog intents
     looked up by literal id ("no-reach-10_0_20_0_24-10_0_30_0_24", "no-reach-10_0_10_0_24-10_0_30_0_24"),
     flipped to run from the host — so on a snapshot without those two subnets the whole test skipped,
     catalog-wide part included. Now every none-reach catalog intent is flipped the same way (the host as
     source, the intent's source subnet as destination) and each role is the first flipped intent with the
     property the tests below need:
      - refuted: a none-reach claim the search refutes with a DELIVERED counterexample;
      - held:    an all-reach claim the search finds no counterexample to, with nothing undecided;
      - mixed:   an all-reach claim with satisfying flows beside undecided ones. */
  type Flipped = { intent: Intent; verdict: ReturnType<typeof runIntentSearch> };
  let flippedMemo: Flipped[] | null = null;
  const flipped = (h: NonNullable<ReturnType<typeof singleGatewayHost>>): Flipped[] => {
    if (flippedMemo !== null) return flippedMemo;
    const src = { ip: h.ip, provenance: "derived" as const, cite: h.cite, note: `a host address inside ${h.host}'s Vlan${h.vlan ?? "?"} subnet` };
    const out: Flipped[] = [];
    for (const base of catalog.filter((i) => i.kind === "none-reach")) {
      const target = base.sourceSpace.prefix;
      for (const kind of ["none-reach", "all-reach"] as const) {
        const intent: Intent = {
          ...base,
          id: `host-${kind}-${base.id}`,
          kind,
          claim: kind === "none-reach" ? `No flow from ${h.ip} reaches ${target}.` : `Every flow from ${h.ip} reaches ${target}.`,
          sources: [src],
          destinations: base.sources,
          sourceSpace: base.destSpace,
          destSpace: base.sourceSpace,
        };
        out.push({ intent, verdict: runIntentSearch(intent) });
      }
    }
    flippedMemo = out;
    return out;
  };
  const hostIntents = (ctx: TestContext): { refuted: Intent; held: Intent; mixed: Intent } => {
    const h = need(ctx, singleGatewayHost(), "host address in a subnet with exactly one gateway");
    const all = flipped(h);
    const refuted = need(
      ctx,
      all.find((f) => f.intent.kind === "none-reach" && f.verdict.counterexamples.some((c) => c.trace.outcome === "delivered")),
      "none-reach intent from a host source refuted by a delivered counterexample",
    ).intent;
    const held = need(
      ctx,
      all.find((f) => f.intent.kind === "all-reach" && f.verdict.outcome === "no-counterexample-found" && f.verdict.undecided === 0),
      "all-reach intent from a host source that holds with nothing undecided",
    ).intent;
    const mixed = need(
      ctx,
      all.find((f) => f.intent.kind === "all-reach" && f.verdict.satisfying > 0 && f.verdict.undecided > 0),
      "all-reach intent from a host source with satisfying flows beside undecided ones",
    ).intent;
    return { refuted, held, mixed };
  };

  it("never offers a counterexample the engine itself says it cannot decide", (ctx) => {
    const counted = { all: 0, delivered: 0 };
    const check = (i: Intent): void => {
      const v = runIntentSearch(i);
      for (const c of v.counterexamples) {
        counted.all += 1;
        expect(c.trace.caveats.some((x) => /never a definite permit/.test(x)), JSON.stringify(c.flow)).toBe(false);
        if (c.trace.outcome === "delivered") {
          counted.delivered += 1;
          expect(isDefiniteDelivery(c.trace)).toBe(true);
        }
      }
    };
    /* The catalog-wide part first: it needs no host subject, so a snapshot without one still runs it. */
    for (const i of catalog) check(i);
    check(hostIntents(ctx).refuted);
    expect(counted.all, "no counterexample was examined").toBeGreaterThan(0);
    expect(counted.delivered, "no delivered counterexample was examined").toBeGreaterThan(0);
  });

  it("never counts an undecided flow as consistent with the intent", (ctx) => {
    const ran = { clean: 0, passesBesideUndecided: 0 };
    const check = (i: Intent): void => {
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
    };
    /* The catalog-wide part first, as above. */
    for (const i of catalog) check(i);
    const h = hostIntents(ctx);
    check(h.held);
    check(h.mixed);
    expect(ran.clean).toBeGreaterThan(0);
    expect(ran.passesBesideUndecided).toBeGreaterThan(0);
  });
});
