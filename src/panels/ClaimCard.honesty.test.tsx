/**
 * ClaimCard.honesty.test.tsx — the card and the hop list draw an undecided outcome as undecided.
 *
 * 2026-09-21 critic findings, over real flows traced by the real engine:
 *  - B1: udp 10.0.30.10 -> 10.0.10.7:53 was badged INDETERMINATE yet drew the green target and
 *    "delivered"; its hop read "delivered — resolved". tcp 10.0.20.50 -> 10.0.10.50:443 is delivered
 *    at core2, which has no collected ACLs, and its hop matched a fully-scoped delivery exactly.
 *  - B8: the "Not established" sentence said "between the same addresses" when the counterexample
 *    had moved the destination, and an undecided denial was offered "the nearest flow that behaves
 *    differently" as if its own verdict were settled.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { Flow } from "../core/types";
import { counterexample, suggestedFlows, traceFlow } from "../forwarding/engine";
import { ClaimCard } from "./ClaimCard";
import { HopList } from "./HopList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  dstPort,
  srcPort: null,
});

function render(f: Flow): HTMLElement {
  const trace = traceFlow(f);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <>
        <ClaimCard trace={trace} counterexample={counterexample(trace.flow, trace)} />
        <HopList trace={trace} activeIndex={null} onSelect={() => {}} />
      </>,
    ),
  );
  return host;
}

describe("an undecided delivery is drawn in the UNDETERMINED band, card and hop", () => {
  for (const [label, f, gap] of [
    ["absence evidence at core1", flow("10.0.30.10", "10.0.10.7", "udp", 53), /binding not observed/],
    ["no ACLs collected at core2", flow("10.0.20.50", "10.0.10.50", "tcp", 443), /no collected ACLs/],
  ] as const) {
    it(label, () => {
      const c = render(f);
      const card = c.querySelector<HTMLElement>(".claim")!;
      expect(card.dataset["band"]).toBe("UNDETERMINED");
      expect(card.querySelector(".claim__outcome-word")?.textContent).toMatch(/not decided/);
      expect(card.querySelector(".claim__sentence")?.textContent).toMatch(gap);
      const verdicts = [...c.querySelectorAll<HTMLElement>(".hop .verdict")];
      expect(verdicts.length).toBeGreaterThan(0);
      for (const v of verdicts) expect(v.dataset["band"], v.textContent ?? "").toBe("UNDETERMINED");
      expect(verdicts.map((v) => v.textContent).join(" ")).not.toMatch(/resolved/);
    });
  }

  it("the flow once drawn as the definite delivery (core1's own address) is not drawn RESOLVED", () => {
    /* REVERSED 2026-09-22 (auditor, B2): 10.0.30.1 is core1's own Vlan30 address, and traffic core1
       originates is refused rather than walked. A definite delivery from a HOST source is drawn
       RESOLVED in src/panels/decided-surfaces.counterfactual.test.tsx. */
    const c = render(flow("10.0.30.1", "10.0.20.10", "tcp", 443));
    expect(c.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("UNDETERMINED");
    expect(c.querySelector(".hop .verdict")).toBeNull();
  });
});

describe("the counterexample block says what actually differs", () => {
  it("draws no counterexample pair beside a router-originated flow (the auditor's 'udp … DELIVERED')", () => {
    /* 2026-09-22 auditor (B2): 10.0.20.2 is core1's own Vlan20 address. The card used to read SCOPED,
       "the gateway port it arrives by had observed filtering", and offered "udp 10.0.20.2 ->
       10.0.10.50:16384 DELIVERED". A self-originated packet has no gateway port and no decided
       outcome, so nothing may be offered against it. The pair's wording ("its protocol (udp instead of
       tcp)") is pinned on a decided host-sourced denial in src/panels/decided-surfaces.counterfactual.test.tsx. */
    const c = render(flow("10.0.20.2", "10.0.10.50", "tcp", 22));
    expect(c.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("UNDETERMINED");
    expect(c.querySelector(".claim__pair")).toBeNull();
    expect(c.querySelector(".claim__counter-outcome")).toBeNull();
    expect(c.textContent ?? "").not.toMatch(/gateway port it arrives by/i);
  });

  it("an undecided denial is not offered a counterexample as if its verdict were settled", () => {
    const c = render(flow("10.0.10.50", "8.8.8.8", "udp", 53));
    expect(c.querySelector<HTMLElement>(".claim")!.dataset["band"]).toBe("UNDETERMINED");
    const titles = [...c.querySelectorAll(".claim__section-title")].map((t) => t.textContent ?? "");
    expect(titles.some((t) => /the nearest flow that behaves differently/.test(t))).toBe(false);
    expect(titles.some((t) => /relative to an UNDECIDED result/.test(t))).toBe(true);
    expect(c.querySelector(".claim__pair")).toBeNull();
  });
});

describe("the counterexample heading does not promise a flow the body does not offer (B8 negative state)", () => {
  /* Acceptance report, B8 observation: "Nearby flow with a different outcome" sat over a body reading
     "None of the 8 nearby variations … so no counterexample is offered". A heading that names a flow
     over a body that offers none is a claim the card then retracts. Class-wide over every flow whose
     card offers nothing: every suggested flow, plus the undecided udp denial pinned above. */
  it("every card whose search offered nothing says so in its heading", () => {
    const flows: Flow[] = [...suggestedFlows().map((s) => s.flow), flow("10.0.10.50", "8.8.8.8", "udp", 53)];
    let negative = 0;
    for (const f of flows) {
      const c = render(f);
      const none = c.querySelector(".claim__counter-none");
      if (none === null) continue;
      negative += 1;
      const title = none.closest(".claim__section")?.querySelector(".claim__section-title")?.textContent ?? "";
      expect(title, `${f.protocol} ${f.srcIp} -> ${f.dstIp}:${f.dstPort ?? "-"}`).toMatch(/\bnone\b/i);
      expect(title).not.toMatch(/the nearest flow that behaves differently/);
      document.body.innerHTML = "";
    }
    // Non-vacuity: this snapshot's negative state is the one the report saw.
    expect(negative).toBeGreaterThan(0);
  });
});
