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
import { counterexample, suggestedFlows, traceFlow, unobservedPolicyInputs } from "../forwarding/engine";
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
  it("the snapshot's own receipts make core2's table incomplete, with the reasons named", () => {
    const labels = ribIncompleteness("core2").map((r) => r.label).join(" | ");
    expect(labels).toMatch(/OSPF is not collected/);
    expect(labels).toMatch(/BGP is not collected/);
    expect(labels).toMatch(/240 received prefixes/);
  });

  it("every no-route suggested flow at a host with an incomplete table bands UNDETERMINED", () => {
    const drops = traces.filter(({ trace }) => trace.outcome === "dropped");
    expect(drops.length, "the snapshot must still offer a no-route flow").toBeGreaterThan(0);
    for (const { id, trace } of drops) {
      const at = trace.hops[trace.hops.length - 1]!.host;
      if (ribIncompleteness(at).length === 0) continue;
      expect(isDecidedOutcome(trace), id).toBe(false);
      expect(bandOfTrace(trace), id).toBe("UNDETERMINED");
      expect(unobservedPolicyInputs(trace).some((g) => g.kind === "rib-partial"), id).toBe(true);
    }
  });

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
       walked router-originated traffic as if it arrived inbound. On this snapshot no trace is decided,
       so only the UNDETERMINED branch can run here, and that is asserted rather than skipped; the
       delivered and blocked branches run on host sources in decided-surfaces.counterfactual.test.tsx. */
    const formerlyDecided = [
      traceFlow({ srcIp: "10.0.30.1", dstIp: "10.0.20.10", protocol: "tcp", dstPort: 22, srcPort: null }),
      traceFlow({ srcIp: "10.0.20.2", dstIp: "10.0.10.50", protocol: "tcp", dstPort: 22, srcPort: null }),
    ];
    for (const t of formerlyDecided) {
      expect(bandOfTrace(t)).toBe("UNDETERMINED");
      expect(traceMarkOf(t)?.kind ?? null).not.toBe("delivered");
      expect(traceMarkOf(t)?.kind ?? null).not.toBe("blocked");
    }
    const ran = { delivered: 0, blocked: 0, undetermined: 0 };
    for (const { id, trace } of traces) {
      const mark = traceMarkOf(trace);
      const band = bandOfTrace(trace);
      if (mark === null) continue;
      ran[mark.kind] += 1;
      if (mark.kind === "delivered") expect(band, id).toBe("RESOLVED");
      if (mark.kind === "blocked") expect(band, id).toBe("REFUTED");
      if (band === "UNDETERMINED") expect(mark.kind, id).toBe("undetermined");
    }
    expect(ran.undetermined).toBeGreaterThan(0);
    /* The critic's exact case was the "permitted" preset, whose core1 hop is undecided. A "permitted"
       preset is offered only for a delivery definite on its modelled path, and on this snapshot every
       such delivery rests on core1's incomplete table (auditor, B1, 2026-09-22) — so it is not offered
       at all, rather than drawn as a delivery. */
    expect(traces.find((t) => t.id === "permitted")).toBeUndefined();
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

  it("an offered nearby flow wears its own band, not a green outcome word", () => {
    /* UPDATED 2026-09-22 (auditor, B1): the suggested denial's nearby variations all rest on core1's
       incomplete table, so none is definite and nothing is offered on this snapshot; a denial is
       never answered by an undecided "delivered". The offered-flow band is pinned in decided-surfaces.counterfactual.test.tsx. */
    const denied = traces.find((t) => t.id === "denied");
    expect(denied).toBeDefined();
    const ce = counterexample(denied!.trace.flow, denied!.trace);
    if (ce.found) {
      const el = mount(<ClaimCard trace={denied!.trace} counterexample={ce} />);
      expect(el.querySelector<HTMLElement>(".claim__counter-outcome")?.dataset.band).toBe(bandOfTrace(ce.trace));
      return;
    }
    expect(ce.reason).toMatch(/nearby variations/);
    const el = mount(<ClaimCard trace={denied!.trace} counterexample={ce} />);
    expect(el.querySelector(".claim__counter-outcome")).toBeNull();
    expect(el.textContent ?? "").not.toMatch(/\bDELIVERED\b/);
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
