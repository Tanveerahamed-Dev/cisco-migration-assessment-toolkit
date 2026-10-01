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
