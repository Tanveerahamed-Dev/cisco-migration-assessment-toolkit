import { describe, expect, it } from "vitest";
import { createPanelInputGate, isFabricTarget } from "./panelInput";

describe("panel input gate", () => {
  it("does not defer when no panel input has arrived", () => {
    const g = createPanelInputGate({ quietMs: 180, maxDeferMs: 900 });
    expect(g.shouldDefer(1000)).toBe(false);
  });

  it("holds an owed render through a typing burst and releases it after the pause", () => {
    const g = createPanelInputGate({ quietMs: 180, maxDeferMs: 900 });
    // Keys every 150 ms: each frame between them is held.
    for (let t = 0; t <= 600; t += 150) {
      g.noteForeignInput(t);
      expect(g.shouldDefer(t + 16)).toBe(true);
      expect(g.shouldDefer(t + 140)).toBe(true);
    }
    // 180 ms after the last key the render lands.
    expect(g.shouldDefer(600 + 180)).toBe(false);
  });

  it("never holds a render longer than maxDeferMs, however long the burst", () => {
    const g = createPanelInputGate({ quietMs: 180, maxDeferMs: 900 });
    let released: number | null = null;
    for (let t = 0; t < 3000; t += 16) {
      if (t % 100 === 0) g.noteForeignInput(t);
      if (!g.shouldDefer(t)) {
        released = t;
        break;
      }
    }
    expect(released).not.toBeNull();
    expect(released as number).toBeLessThanOrEqual(900 + 16);
  });

  it("measures the cap per held render: a landed render restarts it", () => {
    const g = createPanelInputGate({ quietMs: 180, maxDeferMs: 300 });
    g.noteForeignInput(0);
    expect(g.shouldDefer(10)).toBe(true);
    g.rendered();
    g.noteForeignInput(400);
    expect(g.shouldDefer(410)).toBe(true);
    g.noteForeignInput(500);
    expect(g.shouldDefer(600)).toBe(true);
    // 200 ms after the new burst began: under the 300 ms cap, because the cap restarted.
    expect(g.shouldDefer(610)).toBe(true);
  });

  it("input on the fabric releases a held render at once", () => {
    const g = createPanelInputGate({ quietMs: 180, maxDeferMs: 900 });
    g.noteForeignInput(100);
    expect(g.shouldDefer(120)).toBe(true);
    g.noteFabricInput(130);
    expect(g.shouldDefer(140)).toBe(false);
  });

  it("ignores non-finite timestamps rather than holding forever", () => {
    const g = createPanelInputGate();
    g.noteForeignInput(Number.NaN);
    g.noteForeignInput(Number.POSITIVE_INFINITY);
    expect(g.shouldDefer(10)).toBe(false);
  });
});

describe("isFabricTarget", () => {
  it("counts the declared fabric surface, and nothing outside it", () => {
    const host = document.createElement("div");
    host.setAttribute("data-fabric-surface", "");
    const canvas = document.createElement("canvas");
    const label = document.createElement("span");
    host.append(canvas, label);
    const panel = document.createElement("input");
    document.body.append(host, panel);
    expect(isFabricTarget(canvas, canvas)).toBe(true);
    expect(isFabricTarget(canvas, label)).toBe(true);
    expect(isFabricTarget(canvas, panel)).toBe(false);
    expect(isFabricTarget(canvas, null)).toBe(false);
    host.remove();
    panel.remove();
  });

  it("falls back to the canvas alone when no host declares a surface", () => {
    const wrap = document.createElement("div");
    const canvas = document.createElement("canvas");
    const sibling = document.createElement("button");
    wrap.append(canvas, sibling);
    document.body.append(wrap);
    expect(isFabricTarget(canvas, canvas)).toBe(true);
    expect(isFabricTarget(canvas, sibling)).toBe(false);
    wrap.remove();
  });
});
