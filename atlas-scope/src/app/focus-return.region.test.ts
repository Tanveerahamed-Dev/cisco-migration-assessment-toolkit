/**
 * focus-return.region.test.ts — when everything a return record names is gone, focus goes to the
 * region the invoker lived in, not to <body>.
 *
 * THE DEFECT (merged-tree gate, wave 5, 2026-09-24). The Inspector records its invoker when it
 * opens and, on close, returns to it, else to its opener, else to the stage. Below 768 px the stage
 * is `display: none` whenever the fabric is collapsed — so once the invoker had unmounted (the
 * reader moved to another finding while the Inspector stayed open, and the evidence chain that held
 * the citation was re-rendered), every candidate failed and focus fell to <body>.
 * `review/audit-d3-focus.mjs` at 390x844: "phone/inspector (citation) inspector :: close button →
 * Enter -> BODY" and "tab → ArrowRight → Escape -> BODY". The wider widths passed only because the
 * stage fallback happens to be rendered there.
 *
 * The record now also captures, WHILE THE INVOKER EXISTS, the named landmark it sat in, and
 * `returnFocus` tries that region after every stated candidate and the caller's context: the
 * nearest place that still means "where you were".
 */
import { afterEach, describe, expect, it } from "vitest";
import { recordReturn, returnFocus } from "./focus-return";

afterEach(() => {
  document.body.innerHTML = "";
});

function build(): { aside: HTMLElement; invoker: HTMLButtonElement } {
  const aside = document.createElement("aside");
  aside.setAttribute("aria-label", "Evidence");
  const chain = document.createElement("div");
  const invoker = document.createElement("button");
  invoker.textContent = "Open source record punchlist[0]";
  chain.appendChild(invoker);
  aside.appendChild(chain);
  document.body.appendChild(aside);
  return { aside, invoker };
}

describe("returnFocus falls back to the invoker's region", () => {
  it("returns to the invoker while it exists (positive control)", () => {
    const { invoker } = build();
    const record = recordReturn(invoker);
    expect(returnFocus(record, null, [null])).toBe(invoker);
    expect(document.activeElement).toBe(invoker);
  });

  it("lands on the invoker's named region when the invoker and every fallback are gone", () => {
    const { aside, invoker } = build();
    const record = recordReturn(invoker);
    invoker.parentElement!.remove(); // the evidence chain re-rendered: the invoker's subtree is gone
    const landed = returnFocus(record, null, [null]); // the stage fallback: not focusable here
    expect(landed, "focus must not fall to <body>").toBe(aside);
    expect(document.activeElement).toBe(aside);
    // A landmark made focusable only for as long as it holds focus.
    aside.dispatchEvent(new FocusEvent("blur"));
    expect(aside.hasAttribute("tabindex")).toBe(false);
  });

  /* MEASURED on the preview after the first cut of this fix (review/audit-d3-focus.mjs, 390x844):
     focus did land on the region, SECTION "Evidence chain", but a ring drawn round a tall region
     clipped by its rail was "NOT VISIBLE — 780 indicator pixels (floor 1119)". The region's own
     heading names the same place, is small enough to be seen whole, and is where the rest of the
     product lands a reader in that rail (surfaces.tsx railb, CommandPalette's evidence landing). */
  it("lands on the region's heading when it has one, not on the whole region", () => {
    const { aside, invoker } = build();
    const heading = document.createElement("h2");
    heading.textContent = "Evidence chain";
    aside.insertBefore(heading, aside.firstChild);
    const record = recordReturn(invoker);
    invoker.parentElement!.remove();
    const landed = returnFocus(record, null, [null]);
    expect(landed).toBe(heading);
    expect(document.activeElement).toBe(heading);
    heading.dispatchEvent(new FocusEvent("blur"));
    expect(heading.hasAttribute("tabindex"), "made focusable only while it holds focus").toBe(false);
  });

  it("still prefers a stated fallback that can take focus over the region", () => {
    const { invoker } = build();
    const stage = document.createElement("main");
    stage.tabIndex = -1;
    document.body.appendChild(stage);
    const record = recordReturn(invoker);
    invoker.remove();
    expect(returnFocus(record, null, [stage])).toBe(stage);
  });

  it("does not use a region that has itself been removed", () => {
    const { aside, invoker } = build();
    const record = recordReturn(invoker);
    aside.remove();
    expect(returnFocus(record, null, [null])).toBeNull();
  });
});
