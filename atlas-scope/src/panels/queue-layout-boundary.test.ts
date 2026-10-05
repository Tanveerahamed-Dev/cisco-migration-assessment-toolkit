/**
 * Tripwire (source text): the priority queue must stay a relayout boundary and must not become a
 * size container again. Acceptance E3/E5.
 *
 * WHY THIS IS A SOURCE-TEXT TEST. jsdom does no layout, so the cost this guards — a document
 * layout re-resolving all 146 row grids — cannot be observed in the suite at all. It was measured
 * in a real browser (interleaved A/B, release build, median of 50 forced layouts):
 *
 *   dirtying one path-trace form button   20.9 ms -> 6.7 ms   (container-type removed)
 *   dirtying one queue row                45.6 ms -> 25.3 ms  (container-type removed)
 *                                         20.4 ms ->  2.9 ms  (+ `contain: size layout`)
 *
 * and those layouts were the forced-layout time inside every selection commit, every URL
 * `pushState` and every arrow key in the grid. What this file pins is the two declarations that
 * produced the drop, so a later edit that brings `100cqi` back (the obvious way to write a
 * rail-relative width) fails here with the measurement in front of it.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/panels/PriorityQueue.css", "utf8");
/** Declarations only: comments explain the history and are allowed to name what was removed. */
const code = css.replace(/\/\*[\s\S]*?\*\//g, "");

describe("priority queue layout boundary (tripwire: source text)", () => {
  it("is not a size container and resolves no container-relative unit", () => {
    expect(code).not.toMatch(/container-type\s*:/);
    expect(code).not.toMatch(/\d+cq[iwhb]\b|\bcq(min|max)\b/);
  });

  it("feeds the category track from the ResizeObserver-published rail width", () => {
    expect(code).toMatch(/--ag-w-category:\s*clamp\([^;]*var\(--pq-inline/);
    const tsx = readFileSync("src/panels/PriorityQueue.tsx", "utf8");
    expect(tsx).toMatch(/setProperty\("--pq-inline"/);
  });

  it("makes the queue's scroll box a relayout boundary WITHOUT paint containment, fixed-frame layouts only", () => {
    /* Size containment collapses a box that sizes from its content, which the queue does below the
       shell's single-column breakpoint (measured: 12px tall at 390x844). The rule must live inside
       the fixed-frame query, never at top level. */
    const scoped = /@media \(min-width: 48rem\) and \(min-width: 768px\)\s*\{\s*\.pq \.ag__grid\s*\{([^}]*)\}\s*\}/.exec(code);
    expect(scoped, "`.pq .ag__grid` containment must be scoped to @media (min-width: 48rem) and (min-width: 768px)").not.toBeNull();
    const unscoped = code.replace(/@media \(min-width: 48rem\) and \(min-width: 768px\)\s*\{\s*\.pq \.ag__grid\s*\{[^}]*\}\s*\}/, "");
    expect(unscoped).not.toMatch(/\.pq \.ag__grid\s*\{[^}]*contain/);
    const rule = scoped;
    expect(rule, "a `.pq .ag__grid` rule must exist").not.toBeNull();
    const body = rule?.[1] ?? "";
    expect(body).toMatch(/contain:\s*size layout\s*;/);
    // `paint` changed the rows' text anti-aliasing (measured up to 230/255 per channel).
    expect(body).not.toMatch(/paint|strict|content\b/);
  });
});
