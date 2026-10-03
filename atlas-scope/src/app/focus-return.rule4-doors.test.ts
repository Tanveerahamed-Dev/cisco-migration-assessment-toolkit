/**
 * focus-return.rule4-doors.test.ts — rule 4 and "rendered" are ONE statement for every door (independent verifier
 * V1-1 of cluster R-D3).
 *
 * Rule 4 (focus-return.ts): "the region landmark around the element giving focus up — its labelling heading when it
 * is `aria-labelledby` one, else the labelled region itself". The second door's outer walk was repaired to try the
 * heading and THEN the region (focus-return.handoff-hidden.test.ts). The first door (`returnFocus`) and the third
 * (`releaseFocusFrom`) still tried the heading only: MEASURED by the verifier, with the region's heading in a hidden
 * part of it, the third door skipped the region and sent focus to the next tab stop in document order, and the first
 * door focused the hidden heading — which jsdom allows and a browser refuses, so its answer depended on the engine.
 * The same engine dependence was in the first door's own candidates (target, opener, fallbacks): nothing checked
 * they were rendered before focusing them.
 *
 * Each case below states the markup it lays out; jsdom lays nothing out, and "rendered" here is the owner's
 * `isRendered` (the `hidden` attribute, a computed `display: none` on the element or an ancestor, `visibility`).
 */
import { afterEach, describe, expect, it } from "vitest";
import { recordReturn, releaseFocusFrom, returnFocus } from "./focus-return";

afterEach(() => {
  document.body.innerHTML = "";
  document.head.innerHTML = "";
});

/** A region whose labelling heading sits in a hidden part of it, a drawer inside it, and a tab stop after it. */
const HIDDEN_HEADING = `
  <section id="outer" aria-labelledby="outer-title">
    <div hidden><h2 id="outer-title">Sources</h2></div>
    <div id="drawer"><button id="inside">Finding</button></div>
  </section>
  <button id="after">After</button>`;

const $ = (id: string): HTMLElement => document.getElementById(id)!;

describe("the third door states a region by its heading, ELSE THE REGION ITSELF", () => {
  it("the region's heading is hidden: focus goes to the region, not to the next tab stop in document order", () => {
    document.body.innerHTML = HIDDEN_HEADING;
    $("inside").focus();
    const landed = releaseFocusFrom($("drawer"), null);
    expect(landed, "the hidden heading was passed over for the next tab stop, not for the region").toBe($("outer"));
    expect(document.activeElement).toBe($("outer"));
  });

  it("the recorded region is a heading that is now hidden: its region takes focus", () => {
    document.body.innerHTML = `
      <section id="where" aria-labelledby="where-title">
        <h2 id="where-title">Queue</h2>
        <button id="target">Row</button>
      </section>
      <div id="drawer"><button id="inside">Finding</button></div>
      <button id="after">After</button>`;
    const record = recordReturn($("target"));
    expect(record?.region).toBe($("where-title"));
    $("target").remove();
    $("where-title").hidden = true;
    $("inside").focus();
    expect(releaseFocusFrom($("drawer"), record)).toBe($("where"));
  });
});

describe("the first door keeps the same two rules", () => {
  it("the region's heading is hidden: focus goes to the region, never to the hidden heading", () => {
    document.body.innerHTML = HIDDEN_HEADING;
    $("inside").focus();
    $("inside").remove();
    const landed = returnFocus(null, $("drawer"));
    expect(landed, "the first door focused a heading in a hidden subtree").not.toBe($("outer-title"));
    expect(landed).toBe($("outer"));
  });

  it("the recorded target sits in a pane a stylesheet hides: passed over, as a browser would refuse it", () => {
    document.head.innerHTML = `<style>.gone { display: none; }</style>`;
    document.body.innerHTML = `
      <main id="stage" aria-label="Fabric">
        <section class="gone" aria-label="Other pane"><button id="target">Open</button></section>
        <div id="pop"><button id="inside">Copy</button></div>
      </main>`;
    $("inside").focus();
    const landed = returnFocus($("target"), $("pop"));
    expect(landed, "focus went into a pane the stylesheet hides").not.toBe($("target"));
    expect(landed).toBe($("stage"));
  });

  it("a stated fallback that is not rendered is passed over for the next one", () => {
    document.body.innerHTML = `
      <button id="gone" style="display: none">Hidden fallback</button>
      <button id="shown">Shown fallback</button>
      <div id="pop"><button id="inside">Copy</button></div>`;
    $("inside").focus();
    expect(returnFocus(null, $("pop"), [$("gone"), $("shown")])).toBe($("shown"));
  });

  it("the recorded region is a heading that is now hidden: its region takes focus", () => {
    document.body.innerHTML = `
      <section id="where" aria-labelledby="where-title">
        <h2 id="where-title">Queue</h2>
        <button id="target">Row</button>
      </section>`;
    const record = recordReturn($("target"));
    $("target").remove();
    $("where-title").hidden = true;
    expect(returnFocus(record, null)).toBe($("where"));
  });

  it("a rendered target is still the first choice (the rendered check takes nothing a browser would accept)", () => {
    document.body.innerHTML = `<section id="s" aria-label="S"><button id="target">T</button></section><button id="inside">I</button>`;
    $("inside").focus();
    expect(returnFocus($("target"), $("inside"))).toBe($("target"));
  });
});

/* Rule 4 walks OUTWARD at the first door as at the others (independent verifier V2-3 of cluster R-D3). The second
   door (`handOffFocus`) and `releaseFocusLeftUnseen` tried every named region around the element, nearest first; the
   first door tried only the NEAREST region around its context and then the recorded region, so with both of those no
   longer rendered and an outer named region still shown it returned null with focus on <body> — the module's own
   "never land on <body>" broken. MEASURED by the verifier (a scratch test): an aside "Evidence" holding a section
   "Finding" (the opener and its popover) and a sibling section "Device"; the opener recorded; focus in the popover;
   the Finding pane hidden and the popover removed — `returnFocus(rec, pop)` and `returnFocus(rec, opener)` both
   returned null with activeElement BODY, while the same layout through handOffFocus landed on a shown element. */
describe("the first door walks the named regions OUTWARD, like every other door", () => {
  const LAYOUT = `
    <aside id="evidence" aria-label="Evidence">
      <section id="finding" aria-label="Finding">
        <button id="opener" aria-controls="pop">Open the finding's menu</button>
        <div id="pop"><button id="inside">Copy</button></div>
      </section>
      <section id="device" aria-label="Device"><button id="dev">Device</button></section>
    </aside>`;

  it.each([
    ["the removed popover", "pop"],
    ["the recorded opener", "opener"],
  ])("the pane is hidden and the popover removed; context = %s: focus lands on the shown outer region, never <body>", (_what, contextId) => {
    document.body.innerHTML = LAYOUT;
    const record = recordReturn($("opener"));
    const context = $(contextId);
    $("inside").focus();
    $("finding").hidden = true;
    $("pop").remove();
    const landed = returnFocus(record, context);
    expect(document.activeElement, "the first door left focus on <body>").not.toBe(document.body);
    expect(landed, "an outer named region was shown and the first door did not walk to it").toBe($("evidence"));
    expect(document.activeElement).toBe($("evidence"));
    /* Never a SIBLING region: "Device" is not around where the reader was. */
    expect(landed).not.toBe($("device"));
  });

  it("an outer region's heading names it, as rule 4 states every region", () => {
    document.body.innerHTML = LAYOUT.replace(
      `<aside id="evidence" aria-label="Evidence">`,
      `<aside id="evidence" aria-labelledby="evidence-title"><h2 id="evidence-title">Evidence</h2>`,
    );
    const record = recordReturn($("opener"));
    $("inside").focus();
    $("finding").hidden = true;
    $("pop").remove();
    expect(returnFocus(record, $("opener"))).toBe($("evidence-title"));
  });

  it("the nearest region still shown is still the first choice (the walk goes outward only past what is not rendered)", () => {
    document.body.innerHTML = LAYOUT;
    const record = recordReturn($("opener"));
    $("inside").focus();
    $("opener").remove();
    $("pop").remove();
    expect(returnFocus(record, null)).toBe($("finding"));
  });

  /* The walk has TWO halves, each pinned on its own (independent verifier SD3V-4: with the walk around the CONTEXT
     dropped — `[...recorded]` for `[...around.slice(1), ...recorded]` — every test above still passed, since in
     their layout the context and the target share one region chain). Here the context is a PORTALLED popover: it sits
     in a region chain of its own (an overlay layer around a menu), apart from the target's (the Evidence rail). */
  const PORTAL = `
    <aside id="evidence" aria-label="Evidence">
      <section id="finding" aria-label="Finding"><button id="opener">Open the finding's menu</button></section>
    </aside>
    <section id="layer" aria-label="Overlays">
      <section id="menu" aria-label="Finding menu"><button id="inside">Copy</button></section>
    </section>`;

  it("the context's own outer region is walked: only it is shown, and focus lands there, never on <body>", () => {
    document.body.innerHTML = PORTAL;
    const record = recordReturn($("opener"));
    $("inside").focus();
    /* Everything around the target is gone from view; around the context, only the outer layer is left. */
    $("evidence").hidden = true;
    $("menu").hidden = true;
    const landed = returnFocus(record, $("inside"));
    expect(document.activeElement, "the first door left focus on <body>").not.toBe(document.body);
    expect(landed, "the region around the element giving focus up was shown and the first door did not walk to it").toBe($("layer"));
  });

  it("past the nearest region, the context's outer regions come before the target's (rule 4's order)", () => {
    document.body.innerHTML = PORTAL;
    const record = recordReturn($("opener"));
    $("inside").focus();
    /* The target's own region and the context's nearest are hidden; an outer region of EACH chain is shown. */
    $("finding").hidden = true;
    $("menu").hidden = true;
    expect(returnFocus(record, $("inside"))).toBe($("layer"));
  });
});
