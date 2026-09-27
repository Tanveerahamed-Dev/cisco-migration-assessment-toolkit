/**
 * PathTrace.c2-landing.test.tsx — the path panel's own scroller leaves nothing half-drawn (C2).
 *
 * Two measured shapes, both from the C2 overturn (acceptance report, 1440x900, state 06) and the
 * discovery sweep that followed it:
 *   1. The answer landing aligned its target 8 px below the port's top edge whatever sat above it, so
 *      the 8 px band showed the bottom 23% of the preceding citation button ("Open source record
 *      routes.core1[6]") at 1920, 1440 and 768 in both path-result states: a control sliced by a port
 *      the app had just moved. `landingInset` puts the edge in the gap instead.
 *   2. `l3_forwarding[3]` was cut at `.pt-panel`'s bottom edge with no cue there: the mode panels are
 *      the one scroller of the rail that did not opt into the house cut-row scrim. Every mode panel
 *      of the path surface — however many there are — must carry it.
 *
 * jsdom lays nothing out, so the landing geometry is an explicit model (each element's rect is set).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { useInvestigation } from "../core/store";
import { traceFlow } from "../forwarding/engine";
import { actAsync } from "../test-support/act-turns";
import { PathTrace, landingInset } from "./PathTrace";

function place(el: Element, top: number, h: number): void {
  el.getBoundingClientRect = () => ({ x: 0, y: top, width: 300, height: h, top, left: 0, right: 300, bottom: top + h, toJSON: () => ({}) }) as DOMRect;
}

const mounted: Root[] = [];
afterEach(() => {
  for (const r of mounted.splice(0)) act(() => r.unmount());
  document.body.replaceChildren();
  act(() => useInvestigation.getState().reset());
});

describe("C2: the landing's top edge falls in a gap, never through the control above", () => {
  /** A port holding: a fact with a citation button, then the decided fact the landing aligns to. */
  function facts(gap: number): { port: HTMLElement; prevFact: HTMLElement; cite: HTMLElement; decided: HTMLElement } {
    const port = document.createElement("div");
    const hop = document.createElement("div");
    const prevFact = document.createElement("div");
    const cite = document.createElement("button");
    cite.className = "ui-cite";
    cite.textContent = "routes.core1[6]";
    prevFact.appendChild(cite);
    const decided = document.createElement("div");
    decided.setAttribute("data-decided", "");
    hop.append(prevFact, decided);
    port.appendChild(hop);
    document.body.appendChild(port);
    place(port, 0, 500);
    place(hop, 100, 300);
    place(prevFact, 120, 40); // 120-160
    place(cite, 136, 24); // 136-160: the button ends where its fact ends
    place(decided, 160 + gap, 80);
    return { port, prevFact, cite, decided };
  }

  it("the measured shape: a 4 px gap above the decided fact gives a 4 px inset, so no sliver of the citation shows", () => {
    const { port, cite, decided } = facts(4);
    const inset = landingInset(decided, port, 8);
    expect(inset).toBe(4);
    // Land: the port's top edge is at decided.top - inset. The citation must be wholly above it.
    const edge = decided.getBoundingClientRect().top - inset;
    expect(cite.getBoundingClientRect().bottom, "the citation ends at or above the port's edge").toBeLessThanOrEqual(edge);
  });

  it("a wide gap keeps the full pad", () => {
    const { port, decided } = facts(20);
    expect(landingInset(decided, port, 8)).toBe(8);
  });

  it("touching content gives no inset at all (the target lands flush), never a negative one", () => {
    const { port, decided } = facts(0);
    expect(landingInset(decided, port, 8)).toBe(0);
    const overlap = facts(-6);
    expect(landingInset(overlap.decided, overlap.port, 8)).toBe(0);
  });

  it("the content before is found through ancestors when the target is its parent's first child", () => {
    const port = document.createElement("div");
    const before = document.createElement("button");
    const wrap = document.createElement("div");
    const target = document.createElement("h3");
    wrap.appendChild(target);
    port.append(before, wrap);
    document.body.appendChild(port);
    place(port, 0, 500);
    place(before, 50, 30); // 50-80
    place(wrap, 83, 100);
    place(target, 83, 20); // 3 px below the button
    expect(landingInset(target, port, 8)).toBe(3);
  });

  it("a previous sibling that is not laid out is skipped, and nothing before at all keeps the pad", () => {
    const port = document.createElement("div");
    const hidden = document.createElement("div");
    const target = document.createElement("div");
    port.append(hidden, target);
    document.body.appendChild(port);
    place(port, 0, 500);
    hidden.getBoundingClientRect = () => ({ x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, toJSON: () => ({}) }) as DOMRect;
    place(target, 12, 40);
    expect(landingInset(target, port, 8)).toBe(8);
  });
});

/* The landing itself, not only its helper (C2 verifier V3): reverting either call site in
   `landOnAnswer` to the fixed 8 px pad survived every unit test, so only the browser detector would
   have caught it. The real panel is mounted over the real denied trace; jsdom lays nothing out, so
   the geometry is a stated model: the port at 100-500, the blocking hop card at 3000, and whatever
   precedes the aligned element in the document ends GAP px above it — the measured shape (the
   citation button ending a few px above the landed element). The landing must put the port's top
   edge in that gap: scrollTop = aligned.top - port.top - GAP, not - 8. */
describe("C2: the answer landing puts the port's edge in the gap above what it aligns", () => {
  const DENIED = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null } as const;
  const PORT_TOP = 100;
  const HOP_TOP = 3000;
  const GAP = 4;

  /** Mount, run the denied flow, and land with `decidedTop` for the hop's decided fact; `edgeAbove`
   *  names which aligned element the preceding content ends GAP px above. */
  async function landWith(decidedTop: number, edgeAbove: "hop" | "decided"): Promise<{ scrollTop: number; aligned: string }> {
    const proto = HTMLElement.prototype;
    const rectOf = proto.getBoundingClientRect;
    const sh = Object.getOwnPropertyDescriptor(proto, "scrollHeight");
    const ch = Object.getOwnPropertyDescriptor(proto, "clientHeight");
    const style = document.createElement("style");
    style.textContent = ".pt-panel { overflow-y: auto; }";
    document.head.appendChild(style);
    let hop: HTMLElement | null = null;
    let decided: HTMLElement | null = null;
    let before: HTMLElement | null = null;
    const box = (top: number, h: number): DOMRect =>
      ({ x: 0, y: top, width: 300, height: h, top, left: 0, right: 300, bottom: top + h, toJSON: () => ({}) }) as DOMRect;
    proto.getBoundingClientRect = function (this: HTMLElement): DOMRect {
      if (this.classList.contains("pt-panel")) return box(PORT_TOP, 400);
      if (this === hop) return box(HOP_TOP, 800);
      if (this === decided) return box(decidedTop, 60);
      if (before !== null && !this.contains(before) && this.compareDocumentPosition(before) & Node.DOCUMENT_POSITION_FOLLOWING) {
        const top = before === hop ? HOP_TOP : decidedTop;
        return box(top - GAP - 26, 26);
      }
      return box(500, 10);
    };
    Object.defineProperty(proto, "scrollHeight", { configurable: true, get: () => 5000 });
    Object.defineProperty(proto, "clientHeight", { configurable: true, get: () => 400 });
    try {
      expect(traceFlow(DENIED).outcome, "precondition: the flow is still denied").toBe("denied");
      const host = document.createElement("div");
      document.body.appendChild(host);
      const root = createRoot(host);
      mounted.push(root);
      act(() => root.render(<PathTrace id="c2-land" />));
      const panel = host.querySelector<HTMLElement>(".pt-panel")!;
      act(() => useInvestigation.getState().setFlow(DENIED));
      hop = host.querySelector<HTMLElement>('.hop[data-verdict="denied"]');
      expect(hop, "the blocking hop card rendered").not.toBeNull();
      decided = hop!.querySelector<HTMLElement>("[data-decided]");
      expect(decided, "the blocking hop names its decided fact").not.toBeNull();
      before = edgeAbove === "hop" ? hop : decided;
      expect(panel.scrollTop, "an arrived result lands after the next paint").toBe(0);
      await actAsync(async () => {
        await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
      return { scrollTop: panel.scrollTop, aligned: edgeAbove };
    } finally {
      proto.getBoundingClientRect = rectOf;
      if (sh) Object.defineProperty(proto, "scrollHeight", sh);
      if (ch) Object.defineProperty(proto, "clientHeight", ch);
      style.remove();
    }
  }

  it("head alignment: the hop card lands with the port edge in the 4 px gap above it", async () => {
    // The decided fact sits just under the head: head and fact fit together, so the head is aligned.
    const { scrollTop } = await landWith(HOP_TOP + 50, "hop");
    expect(scrollTop, "the port edge falls in the gap above the hop, not 8 px up through the control above").toBe(HOP_TOP - PORT_TOP - GAP);
  });

  it("decided alignment: the deciding fact lands with the port edge in the 4 px gap above it", async () => {
    // The decided fact is far below the head: it cannot fit with the head, so the fact is aligned.
    const { scrollTop } = await landWith(HOP_TOP + 500, "decided");
    expect(scrollTop, "the port edge falls in the gap above the decided fact, not 8 px up through the citation").toBe(HOP_TOP + 500 - PORT_TOP - GAP);
  });
});

describe("C2: every mode panel of the path surface carries the cut-row scrim", () => {
  it("each tabpanel under the path investigation is a scrim scroller", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    mounted.push(root);
    act(() => root.render(<PathTrace id="c2-path" />));
    const section = host.querySelector('section[aria-label="Path investigation"]');
    expect(section, "the path panel rendered").not.toBeNull();
    const panels = [...section!.querySelectorAll<HTMLElement>('[role="tabpanel"]')];
    const tabs = [...section!.querySelectorAll('[role="tab"]')];
    expect(panels.length, "one panel per mode tab (hidden panels included)").toBe(tabs.length);
    expect(panels.length).toBeGreaterThan(0);
    const missing = panels.filter((p) => !p.classList.contains("scroll-scrim")).map((p) => p.id);
    expect(missing, "mode panels that own a scroller without the cut-row cue").toEqual([]);
  });

  /* C2 verifier V4: the scrim's cover (background-attachment: local) is painted in
     --scroll-scrim-bg, and shell.css's own rule is that the fill is NAMED as the surface's ground so
     the cover is invisible at rest. `.rail .scroll-scrim` names the rail's --surface-1, but the path
     surface paints its own ground (PathTrace.css `.pathtrace`), so the cover painted a --surface-1
     band where the list ends. Both values are read from their CSS owners, not restated here. */
  it("each scrim panel's cover is the path surface's own ground, not the rail's", () => {
    const css = (f: string): string => readFileSync(resolve(__dirname, f), "utf8");
    /** The declared value of `prop` in the first rule whose selector list includes `selector`. */
    const declared = (text: string, selector: string, prop: string): string | undefined => {
      for (const m of text.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
        const selectors = (m[1] ?? "").replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim());
        if (!selectors.includes(selector)) continue;
        const v = new RegExp(String.raw`(?:^|;|\s)${prop}\s*:\s*([^;]+);`).exec(m[2] ?? "")?.[1]?.trim();
        if (v !== undefined) return v;
      }
      return undefined;
    };
    const ground = declared(css("PathTrace.css"), ".pathtrace", "background");
    expect(ground, "PathTrace.css paints the path surface's ground on .pathtrace").toBeTruthy();
    const railFill = declared(css("../app/shell.css"), ".rail .scroll-scrim", "--scroll-scrim-bg");
    expect(railFill, "precondition: shell.css names a rail fill for scrims inside a rail").toBeTruthy();
    expect(railFill, "precondition: the rail's fill is not the path surface's ground (else nothing to override)").not.toBe(ground);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    mounted.push(root);
    act(() => root.render(<PathTrace id="c2-ground" />));
    const panels = [...host.querySelectorAll<HTMLElement>('section[aria-label="Path investigation"] [role="tabpanel"].scroll-scrim')];
    expect(panels.length).toBeGreaterThan(0);
    const wrong = panels
      .map((p) => ({ id: p.id, fill: p.style.getPropertyValue("--scroll-scrim-bg").trim() }))
      .filter((p) => p.fill !== ground);
    expect(wrong, `scrim panels whose cover is not the path surface's ground (${ground})`).toEqual([]);
  });
});
