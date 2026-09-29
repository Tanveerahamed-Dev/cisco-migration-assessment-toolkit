/**
 * claim-honesty-b1.test.tsx — the 2026-09-21 critic's B1/B5/B6 claim-honesty findings, pinned over
 * REAL engine output against the compiled snapshot (never a synthetic trace).
 *
 *  1. A no-route drop on a routing table the snapshot shows to be incomplete is UNDECIDED, and the
 *     intent search over such drops cannot report "no counterexample found".
 *  2. Every surface that draws an outcome — the preset list, the counterexample, the 3-D trace mark —
 *     follows the trace's band, never the raw outcome word.
 *  3. An evidence item's citation reaches a record that carries the field its `raw` text quotes.
 *  4. Every ACL line some source cannot decide is flagged inline in the device pane's line list.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { aclUndecidability } from "../core/acl-coverage";
import { bandOfTrace, isDecidedOutcome, outcomeUndecidingGaps } from "../core/claims";
import { aclsOf, fabric } from "../core/data";
import type { Trace } from "../core/types";
import { counterexample, isDefiniteDelivery, suggestedFlows, traceFlow, unobservedPolicyInputs } from "../forwarding/engine";
import { describeGolden } from "../test-support/golden-sample";
import { flowLabel, universeTraces } from "./trace-universe";
import { ribIncompleteness } from "../forwarding/rib-completeness";
import { traceMarkOf } from "../fabric3d/Fabric3D";
import { ClaimCard } from "./ClaimCard";
import { AclLines } from "./DevicePane";
import { resolveCitation } from "./Inspector";
import { PathTrace, intentCatalog, runIntentSearch } from "./PathTrace";

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

const traces: { id: string; trace: Trace }[] = suggestedFlows().map((s) => ({ id: s.id, trace: traceFlow(s.flow) }));

describe("a drop on an incomplete routing table is not decided", () => {
  /* core2's reasons are facts about the reference sample: golden tier (phase 3 rename leg). */
  describeGolden("the reference sample's partial table", () => {
    it("the snapshot's own receipts make core2's table incomplete, with the reasons named", () => {
      const labels = ribIncompleteness("core2").map((r) => r.label).join(" | ");
      expect(labels).toMatch(/OSPF is not collected/);
      expect(labels).toMatch(/BGP is not collected/);
      expect(labels).toMatch(/240 received prefixes/);
    });
  });

  /* "every no-route suggested flow at a host with an incomplete table bands UNDETERMINED" moved 2026-09-28
     (phase 3) to claim-honesty.no-route.counterfactual.test.tsx, unchanged in what it asserts and widened
     from the suggested flows to every no-route drop: the regenerated sample gave every collected table a
     default route, so no trace of the real snapshot is dropped any more ("the snapshot must still offer a
     no-route flow: expected 0 to be greater than 0"). */

  it("the same ingress-alternate gap undecides a drop exactly as it undecides a denial", () => {
    for (const { id, trace } of traces) {
      if (trace.outcome !== "dropped" && trace.outcome !== "denied") continue;
      if (unobservedPolicyInputs(trace).some((g) => g.kind === "ingress-alternate")) {
        expect(isDecidedOutcome(trace), id).toBe(false);
        expect(outcomeUndecidingGaps(trace).length, id).toBeGreaterThan(0);
      }
    }
  });

  it("a none-reach intent resting on those drops is not reported as a clean sweep, and names the partial table", () => {
    for (const intent of intentCatalog().filter((i) => i.kind === "none-reach")) {
      const v = runIntentSearch(intent);
      const partialTouched = v.hostsTouched.filter((h) => fabric.coverage.routableHosts.includes(h) && ribIncompleteness(h).length > 0);
      if (v.outcome === "no-counterexample-found") {
        // Only allowed when nothing the search rested on was an incomplete table's "no route".
        expect(v.undecided).toBe(0);
      }
      for (const h of partialTouched) expect(v.boundSentence, intent.id).toContain(`${h}'s collected routing table is itself incomplete`);
    }
    const vlan20 = intentCatalog().find((i) => i.id.startsWith("no-reach-10_0_20_0_24"));
    expect(vlan20).toBeDefined();
    const v = runIntentSearch(vlan20!);
    expect(v.outcome).not.toBe("no-counterexample-found");
    expect(v.undecided).toBe(v.searched);
  });
});

describe("every surface that draws an outcome follows the trace's band", () => {
  it("the 3-D trace mark never claims more than the trace band (real traces)", () => {
    /* UPDATED 2026-09-22 (auditor, B1 + B2). The two flows once added to reach the delivered and
       blocked branches were sourced by core1's own SVI addresses — decided only because the engine
       walked router-originated traffic as if it arrived inbound. They stay UNDETERMINED here. */
    const formerlyDecided = [
      traceFlow({ srcIp: "10.0.30.1", dstIp: "10.0.20.10", protocol: "tcp", dstPort: 22, srcPort: null }),
      traceFlow({ srcIp: "10.0.20.2", dstIp: "10.0.10.50", protocol: "tcp", dstPort: 22, srcPort: null }),
    ];
    for (const t of formerlyDecided) {
      expect(bandOfTrace(t)).toBe("UNDETERMINED");
      expect(traceMarkOf(t)?.kind ?? null).not.toBe("delivered");
      expect(traceMarkOf(t)?.kind ?? null).not.toBe("blocked");
    }
    /* RE-EXPRESSED 2026-09-28 (phase 3). On the old sample no trace was decided, so only the
       UNDETERMINED branch could run here, and the "permitted" preset was pinned as NOT offered. The
       regenerated sample has decided multi-hop traces from HOST sources, so every branch now runs on real
       evidence: the suggested flows plus the snapshot's first decided delivery and decided denial, found
       by property. The critic's case — a "permitted" preset whose hop is undecided — is still held to its
       band by the same loop wherever the engine offers it. */
    const decided = [
      universeTraces().find((t) => isDefiniteDelivery(t)),
      universeTraces().find((t) => t.outcome === "denied" && isDecidedOutcome(t)),
    ].flatMap((t, i) => (t === undefined ? [] : [{ id: i === 0 ? "decided delivery" : "decided denial", trace: t }]));
    const ran = { delivered: 0, blocked: 0, undetermined: 0 };
    for (const { id, trace } of [...traces, ...decided]) {
      const mark = traceMarkOf(trace);
      const band = bandOfTrace(trace);
      if (mark === null) continue;
      ran[mark.kind] += 1;
      if (mark.kind === "delivered") expect(band, id).toBe("RESOLVED");
      if (mark.kind === "blocked") expect(band, id).toBe("REFUTED");
      if (band === "UNDETERMINED") expect(mark.kind, id).toBe("undetermined");
    }
    expect(ran.undetermined).toBeGreaterThan(0);
    const permitted = traces.find((t) => t.id === "permitted");
    if (permitted !== undefined && bandOfTrace(permitted.trace) === "UNDETERMINED") expect(traceMarkOf(permitted.trace)?.kind).toBe("undetermined");
  });

  describeGolden("the reference sample's decided marks", () => {
    it("its decided delivery and decided denial are drawn as a delivery and a block", () => {
      const delivery = universeTraces().find((t) => isDefiniteDelivery(t));
      const denial = universeTraces().find((t) => t.outcome === "denied" && isDecidedOutcome(t));
      expect(traceMarkOf(delivery!)?.kind).toBe("delivered");
      expect(traceMarkOf(denial!)?.kind).toBe("blocked");
    });
  });

  it("state 06: the 3-D chip's ending and the path panel's verdict come from one owner and agree", () => {
    /* The D8 refuter's question (acceptance report, 2026-09-22): in state 06 the path panel reads
       "… on core1 denies this flow" while the 3-D chip reads "? UNDECIDED". Investigated: the chip's
       ending is `traceMarkOf` (Fabric3D.tsx), which reads the claim owner's `bandOfHopIn` /
       `bandOfTrace` — the same owner ClaimCard's badge and HopList read. "denies this flow" is the
       ACL line's own evidence text quoted INSIDE the undecided card ("That denial is not decided"),
       not a verdict. So the two agree; this pins it on the exact flow the capture uses. */
    const t = traceFlow({ srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null });
    expect(t.outcome, "precondition: the engine's raw outcome word is a denial").toBe("denied");
    expect(bandOfTrace(t)).toBe("UNDETERMINED");
    expect(traceMarkOf(t)?.kind, "the 3-D chip's ending").toBe("undetermined");
    const el = mount(<ClaimCard trace={t} counterexample={counterexample(t.flow, t)} />);
    const card = el.textContent ?? "";
    expect(card).toMatch(/not decided/);
    expect(card).not.toMatch(/\bBLOCKED\b|\bDENIED\b/);
  });

  it("the preset list draws every undecided flow as undecided", () => {
    const el = mount(<PathTrace />);
    const rows = [...el.querySelectorAll<HTMLElement>(".pt-preset__outcome")];
    expect(rows.length).toBe(traces.length);
    rows.forEach((row, i) => {
      const { id, trace } = traces[i]!;
      expect(row.dataset.band, id).toBe(bandOfTrace(trace));
      if (bandOfTrace(trace) === "UNDETERMINED" && (trace.outcome === "delivered" || trace.outcome === "denied" || trace.outcome === "dropped")) {
        expect(row.textContent, id).toMatch(/not decided/);
      }
    });
  });

  /* RE-EXPRESSED 2026-09-28 (phase 3). This asserted that the suggested undecided denial is offered NO
     nearby flow, and said so: "if a nearby flow ever becomes definite here, this fails first and the
     title gets revisited". The regenerated sample does offer one (the same source to port 22, delivered
     on the modelled path) — so the test is revisited as it asked. What it guards is unchanged: a card over
     an UNDECIDED denial never presents a nearby flow as a counterexample, never draws the intended /
     not-established pair (which reads the baseline as settled), and never lets the nearby flow's outcome
     wear a band stronger than that flow's own. Both branches — something offered, nothing offered — are
     now found by property in the snapshot's flow universe and each is checked where it exists. */
  it("an undecided denial's card never presents a nearby flow as a counterexample, offered or not", () => {
    const undecidedDenials = universeTraces().filter((t) => t.outcome === "denied" && !isDecidedOutcome(t));
    expect(undecidedDenials.length, "precondition: this snapshot has an undecided denial").toBeGreaterThan(0);
    const offered = undecidedDenials.find((t) => counterexample(t.flow, t).found);
    const none = undecidedDenials.find((t) => !counterexample(t.flow, t).found);
    let checked = 0;
    for (const t of [offered, none]) {
      if (t === undefined) continue;
      checked += 1;
      const ce = counterexample(t.flow, t);
      const el = mount(<ClaimCard trace={t} counterexample={ce} />);
      const titles = [...el.querySelectorAll(".claim__section-title")].map((x) => x.textContent ?? "");
      expect(titles.some((x) => /the nearest flow that behaves differently/.test(x)), flowLabel(t.flow)).toBe(false);
      expect(titles.some((x) => /relative to an UNDECIDED result/.test(x)), flowLabel(t.flow)).toBe(true);
      expect(el.querySelector(".claim__pair"), flowLabel(t.flow)).toBeNull();
      const outcome = el.querySelector<HTMLElement>(".claim__counter-outcome");
      if (ce.found) {
        expect(outcome?.dataset["band"], "the nearby flow wears its OWN band").toBe(bandOfTrace(ce.trace));
      } else {
        expect(ce.reason).toMatch(/nearby variations/);
        expect(outcome).toBeNull();
        expect(el.textContent ?? "").not.toMatch(/\bDELIVERED\b/);
      }
      act(() => mounted.pop()!.unmount());
    }
    expect(checked, "at least one undecided-denial card was drawn").toBeGreaterThan(0);
  });

  describeGolden("the reference sample's undecided denials", () => {
    it("the suggested denial is offered a nearby flow, and some undecided denial is offered none — both branches run", () => {
      const denied = traces.find((t) => t.id === "denied");
      expect(denied, "the suggested denial").toBeDefined();
      expect(isDecidedOutcome(denied!.trace)).toBe(false);
      expect(counterexample(denied!.trace.flow, denied!.trace).found).toBe(true);
      expect(universeTraces().some((t) => t.outcome === "denied" && !isDecidedOutcome(t) && !counterexample(t.flow, t).found)).toBe(true);
    });
  });
});

describe("a citation reaches the record that carries its claim", () => {
  it("for every `field: value` evidence item, the Inspector shows a record holding that value", () => {
    const camel = (s: string): string => s.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
    let checked = 0;
    for (const { trace } of traces) {
      for (const hop of trace.hops) {
        for (const e of [...hop.evidence, ...(hop.decidedBy === null ? [] : [hop.decidedBy])]) {
          const m = e.raw === null ? null : /^([a-z_]+): (\S+)$/.exec(e.raw);
          if (m === null) continue;
          const [, field, value] = m;
          const r = resolveCitation(e.cite);
          const shown = [r.record, ...r.companions.map((c) => c.record)] as Record<string, unknown>[];
          const holds = shown.some((rec) => rec !== null && typeof rec === "object" && (rec[field!] === value || rec[camel(field!)] === value));
          expect(holds, `${e.cite} quotes "${e.raw}" but no shown record carries it`).toBe(true);
          checked++;
        }
      }
    }
    expect(checked, "at least one binding evidence item must be exercised").toBeGreaterThan(0);
  });
});

describe("every undecidable ACL line is flagged where it is listed", () => {
  it("each member of the undecidable union carries an inline flag in AclLines", () => {
    const members = aclUndecidability().members;
    expect(members.length).toBeGreaterThan(0);
    for (const host of new Set(members.map((m) => m.host))) {
      for (const [name, lines] of Object.entries(aclsOf(host))) {
        const el = mount(<AclLines lines={lines} onOpenCite={() => {}} />);
        for (const m of members.filter((x) => x.host === host && x.acl === name)) {
          const li = [...el.querySelectorAll<HTMLElement>(".dp-acl__line")].find((x) => x.textContent?.includes(m.cite));
          expect(li, m.label).toBeDefined();
          expect(li!.querySelector(".dp-acl__flag"), `${m.label} is undecidable but unflagged`).not.toBeNull();
        }
      }
    }
  });
});
