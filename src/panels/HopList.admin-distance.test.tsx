/**
 * HopList.admin-distance.test.tsx — one structural null, one set of words, on every surface.
 *
 * THE DEFECT (2026-09-23 acceptance report, B1 item 14). For the same record — a connected route
 * whose `adminDistance` is null — the Inspector rendered "0 — a connected route's administrative
 * distance by definition" while the hop list rendered "not observed". One of them was wrong about
 * the evidence, and a reader comparing the two surfaces could not tell which. The owner of "is this
 * null structural?" is `claims.ts :: notApplicableReason`; the Inspector read it and the hop list did
 * not.
 *
 * THE CLASS, NOT THE FIELD. Every route field the hop list renders from a record goes through the
 * same owner, so the test walks every route record in the snapshot whose null the owner calls
 * structural — for each such field — and asserts the hop list's words are the Inspector's words.
 * The records are found from the compiled data, never listed.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { notApplicableReason } from "../core/claims";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Flow, Trace } from "../core/types";
import { traceFlow } from "../forwarding/engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "../forwarding/ip";
import { HopList } from "./HopList";
import { Inspector, setInspectorCite } from "./Inspector";

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
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setInspectorOpen(false);
  });
  setInspectorCite(null);
});

const squash = (s: string | null | undefined): string => (s ?? "").replace(/\s+/g, " ").trim();

/** The route fields the hop list renders from a route record. */
const ROUTE_FIELDS = ["adminDistance", "nextHop"] as const;

/* Flows from one observed subnet to a host address in every other observed subnet: every connected
   route the collected RIBs hold is then the winner or a beaten alternative on some hop. Derived
   from the snapshot's own L3 records, not typed in. */
const SUBNETS = [...new Map(fabric.l3.flatMap((r) => {
  const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
  return a === null ? [] : [[`${a.prefix.base}/${a.prefix.bits}`, a.prefix] as const];
})).values()];
const TRACES: Trace[] = SUBNETS.flatMap((from) =>
  SUBNETS.flatMap((to) => {
    const src = hostAddressIn(from, 50);
    const dst = hostAddressIn(to, 10);
    if (src === null || dst === null || from === to) return [];
    const flow: Flow = { srcIp: formatIpv4(src), dstIp: formatIpv4(dst), protocol: "tcp", dstPort: 443, srcPort: null };
    return [traceFlow(flow)];
  }),
);

/** The Inspector's rendered words for one field of the record a cite names. */
function inspectorWords(cite: string, field: string): string {
  const c = mount(<Inspector cite={cite} forceOpen />);
  const row = [...c.querySelectorAll("#inspector-panel-data .insp-kv__row")].find(
    (r) => squash(r.querySelector(".insp-kv__key")?.textContent) === field,
  );
  if (row === undefined) throw new Error(`the Inspector shows no ${field} row for ${cite}`);
  return squash(row.querySelector(".insp-kv__val")?.textContent);
}

describe("a structural null in a route renders the same words in the hop list and the Inspector", () => {
  it("rests on at least one connected route with no recorded administrative distance on a traced hop", () => {
    const hit = TRACES.some((t) =>
      t.hops.some((h) => h.evidence.some((e) => e.kind === "route" && /routes\.[^[]+\[\d+\]/.test(e.cite))),
    );
    expect(hit).toBe(true);
    const structural = Object.values(fabric.routes).flat().filter((r) => notApplicableReason(r, "adminDistance") !== null);
    expect(structural.length, "precondition: the snapshot holds a connected/local route with a null AD").toBeGreaterThan(0);
  });

  it("the reported instance: the winning connected route of a delivered hop, AD null", () => {
    /* Whichever traced hop WON on a connected route with a null AD — found, not named. */
    let found: { t: Trace; cite: string } | null = null;
    for (const t of TRACES) {
      for (const h of t.hops) {
        for (const e of h.evidence) {
          if (e.kind !== "route" || found !== null) continue;
          const m = /^routes\.([^[]+)\[(\d+)\]$/.exec(e.cite);
          const r = m ? fabric.routes[m[1]!]?.[Number(m[2])] : undefined;
          if (r !== undefined && r.adminDistance === null && notApplicableReason(r, "adminDistance") !== null) found = { t, cite: e.cite };
        }
      }
    }
    expect(found, "precondition: some traced hop took a connected route with a null AD").not.toBeNull();
    const c = mount(<HopList trace={found!.t} activeIndex={0} onSelect={() => {}} />);
    const fact = [...c.querySelectorAll(".hop__fact")].find(
      (f) => f.querySelector(".hop__key")?.textContent?.startsWith("Route") && f.querySelector(`[aria-label="Open source record ${found!.cite}"]`) !== null,
    );
    expect(fact, `no Route row cites ${found!.cite}`).toBeDefined();
    const inspector = inspectorWords(found!.cite, "adminDistance");
    expect(inspector).toMatch(/^0 — a (connected|local) route's administrative distance by definition/);
    expect(squash(fact!.textContent)).toContain(inspector);
    expect(squash(fact!.textContent)).not.toMatch(/administrative distance: not observed/);
  });

  it("every rendered route field whose null is structural reads exactly as the Inspector reads it", () => {
    let compared = 0;
    for (const t of TRACES) {
      if (t.hops.length === 0) continue;
      const c = mount(<HopList trace={t} activeIndex={0} onSelect={() => {}} />);
      for (const cell of c.querySelectorAll<HTMLElement>("[data-route-field]")) {
        const field = cell.dataset["routeField"]!;
        const cite = cell.dataset["routeCite"]!;
        const record = (fabric.routes[/^routes\.([^[]+)\[/.exec(cite)?.[1] ?? ""] ?? [])[Number(/\[(\d+)\]$/.exec(cite)?.[1])];
        expect(record, `the hop list cites ${cite}, which does not resolve`).toBeDefined();
        const na = notApplicableReason(record, field);
        if (na === null) continue;
        const words = squash(cell.textContent);
        expect(words, `${cite}.${field} in the hop list`).toBe(na);
        expect(words).not.toMatch(/not observed/);
        expect(inspectorWords(cite, field), `${cite}.${field} in the Inspector`).toBe(words);
        compared += 1;
      }
      for (const m of mounted.splice(0)) {
        act(() => m.root.unmount());
        m.container.remove();
      }
    }
    // Both fields, and more than one record: a comparison that never ran proves nothing.
    expect(compared, "no structural null was compared at all").toBeGreaterThan(1);
  });

  it("marks every route field it renders, so none can escape the comparison above", () => {
    const t = TRACES.find((x) => x.hops.some((h) => h.alternatives.length > 0))!;
    const c = mount(<HopList trace={t} activeIndex={0} onSelect={() => {}} />);
    const fields = new Set([...c.querySelectorAll<HTMLElement>("[data-route-field]")].map((e) => e.dataset["routeField"]));
    for (const f of ROUTE_FIELDS) expect(fields.has(f), `no rendered ${f} carries data-route-field`).toBe(true);
  });
});
