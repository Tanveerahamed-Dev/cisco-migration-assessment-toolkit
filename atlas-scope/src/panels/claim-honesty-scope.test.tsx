/**
 * claim-honesty-scope.test.tsx — every trace carries its scope claim and a non-empty caveat list, and the
 * card draws both, on whatever snapshot is loaded (phase 3, 2026-09-28).
 *
 * The regenerated sample turned one-hop, never-decided traces into decided multi-hop ones, and the scope's
 * denominator from "2 of 26" into "4 of 26" RIB hosts. The honesty rule that must survive such a change
 * is not a number: every result states what it rests on — the scope clause naming the collected RIBs it
 * was computed under, with the count read from the snapshot's coverage — and every result carries at least
 * one caveat, decided or not. So this runs over the snapshot's whole flow universe (trace-universe.ts),
 * every outcome, and reads every expected count from the compiled coverage rather than typing it.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { bandOfTrace } from "../core/claims";
import { fabric } from "../core/data";
import type { Trace } from "../core/types";
import { scopeClauseOf } from "../forwarding/engine";
import { describeGolden } from "../test-support/golden-sample";
import { ClaimCard } from "./ClaimCard";
import { splitCited } from "./cited-text";
import { flowLabel, universeTraces } from "../test-support/trace-universe";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const norm = (s: string): string => s.replace(/\s+/g, " ").trim();
/** A caveat's words with its citations masked, as the reader sees them (each citation is a link of its own). */
const maskedWords = (caveat: string): string => norm(splitCited(caveat).map((p) => ("cite" in p ? " " : p.text)).join(""));
const citeCount = (caveat: string): number => splitCited(caveat).filter((p) => "cite" in p).length;
/** A drawn caveat's words with its citation links removed, and how many citation links it drew. */
function drawnCaveat(li: Element): { words: string; cites: number } {
  const copy = li.cloneNode(true) as Element;
  const links = [...copy.querySelectorAll(".cited-text__cite")];
  for (const a of links) a.replaceWith(" ");
  return { words: norm(copy.textContent ?? ""), cites: links.length };
}

const roots: Root[] = [];
afterEach(() => {
  for (const r of roots.splice(0)) act(() => r.unmount());
  document.body.innerHTML = "";
});

describe("every trace states the scope it rests on and its caveats", () => {
  it("each trace of the universe — every outcome — has a scope clause that opens its claim, naming the RIB denominator read from the coverage", () => {
    const traces = universeTraces();
    expect(traces.length, "precondition: the snapshot poses flows").toBeGreaterThan(0);
    const denominator = `${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length} hosts`;
    const bad: string[] = [];
    for (const t of traces) {
      const scope = scopeClauseOf(t);
      if (scope === null) bad.push(`${flowLabel(t.flow)} (${t.outcome}): no scope clause`);
      else if (!t.claim.startsWith(scope)) bad.push(`${flowLabel(t.flow)}: the claim does not open with its scope`);
      else if (!scope.includes(denominator)) bad.push(`${flowLabel(t.flow)}: the scope does not name ${denominator}: ${scope}`);
    }
    expect(bad).toEqual([]);
  });

  it("each trace of the universe carries at least one caveat, and no caveat is blank", () => {
    const bad = universeTraces()
      .filter((t) => t.caveats.length === 0 || t.caveats.some((c) => c.trim() === ""))
      .map((t) => `${flowLabel(t.flow)} (${t.outcome}, ${bandOfTrace(t)})`);
    expect(bad).toEqual([]);
  });

  it("the card draws the scope and every caveat, for one trace of each outcome and band", () => {
    const shapes = new Map<string, Trace>();
    for (const t of universeTraces()) {
      const k = `${t.outcome}/${bandOfTrace(t)}`;
      if (!shapes.has(k)) shapes.set(k, t);
    }
    expect(shapes.size, "precondition: more than one outcome").toBeGreaterThan(1);
    for (const t of shapes.values()) {
      const el = document.createElement("div");
      document.body.appendChild(el);
      const root = createRoot(el);
      roots.push(root);
      act(() => root.render(<ClaimCard trace={t} />));
      const body = (el.textContent ?? "").replace(/\s+/g, " ");
      expect(body, flowLabel(t.flow)).toContain(`${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length} hosts`);
      const drawn = [...el.querySelectorAll(".claim__caveats > li")];
      expect(drawn.length, flowLabel(t.flow)).toBe(t.caveats.length);
      /* Verifier V4: the count alone let a card draw every caveat BLANK. Each drawn caveat is the engine's
         own sentence, in order — its words with citations masked, and one citation link per cited record. */
      drawn.forEach((li, i) => {
        const c = t.caveats[i]!;
        const got = drawnCaveat(li);
        expect(got.words, `${flowLabel(t.flow)} caveat ${i}`).toBe(maskedWords(c));
        expect(got.words.length, `${flowLabel(t.flow)} caveat ${i} is blank`).toBeGreaterThan(0);
        expect(got.cites, `${flowLabel(t.flow)} caveat ${i} citations`).toBe(citeCount(c));
      });
    }
  });
});

describeGolden("the reference sample's denominator and outcome shapes", () => {
  it("four collected RIBs of 26 hosts, and decided outcomes of both bands among its traces", () => {
    expect(`${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length}`).toBe("4 of 26");
    const bands = new Set(universeTraces().map((t) => `${t.outcome}/${bandOfTrace(t)}`));
    expect([...bands]).toEqual(expect.arrayContaining(["delivered/RESOLVED", "denied/REFUTED", "delivered/UNDETERMINED", "denied/UNDETERMINED"]));
  });
});
