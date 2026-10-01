/**
 * focus-return.handoff-hidden.test.ts — independent verification of the phase-3.5 close gate's change to the
 * SECOND DOOR (`handOffFocus`, R129/O77): the outward-landmark walk and the "never into a hidden subtree" check,
 * judged against rule 4 of focus-return.ts.
 *
 * WHAT THE GATE CHANGED. A self-removing control whose action ALSO hides its whole surface ("Select <host>" in
 * the Finding pane selects a device, and the rail hides the Finding pane) used to hand focus to a sibling or a
 * landmark inside the hidden pane; the gate made the hand-off skip candidates inside a `[hidden]` subtree and
 * walk outward to the next named region.
 *
 * WHAT THIS FILE FOUND (red before the fix):
 *   1. "Hidden" meant the `hidden` ATTRIBUTE only — a named subset standing in for the class "not rendered". A
 *      surface hidden by its stylesheet (`display: none`, as every rung of the ladder hides a pane) was still a
 *      candidate. A browser refuses focus() there so the walk went on; jsdom accepts it, so the owner's answer
 *      depended on the engine — the very dependence the gate's own comment set out to remove. The check is now
 *      the owner's one statement of "rendered" (`isRendered`, which the fourth door already uses), and the THIRD
 *      door's candidate filter, which the gate's comment cites as the rule it copied, had the same subset.
 *   2. Rule 4 says a region is stated by its labelling heading, ELSE THE REGION ITSELF. The outer walk tried only
 *      the stated element, so a shown region whose heading sat in a hidden part of it was skipped for the next
 *      region out (or for nothing), though the region itself could take focus.
 */
import { afterEach, describe, expect, it } from "vitest";
import { handOffFocus, releaseFocusFrom } from "./focus-return";

/** Let the hand-off's microtask and its first timers run. */
const settle = (): Promise<void> => new Promise((done) => setTimeout(done, 60));

afterEach(() => {
  document.body.innerHTML = "";
  document.head.innerHTML = "";
});

describe("the second door never hands focus into a surface that is not rendered, however it was hidden", () => {
  for (const [how, hide] of [
    ["the hidden attribute", (el: HTMLElement) => (el.hidden = true)],
    ["a stylesheet display:none", (el: HTMLElement) => el.classList.add("gone")],
    ["an inline display:none", (el: HTMLElement) => (el.style.display = "none")],
  ] as const) {
    it(`the control's pane is hidden by ${how}: focus goes to the next SHOWN region out, never into the pane`, async () => {
      document.head.innerHTML = `<style>.gone { display: none; }</style>`;
      document.body.innerHTML = `
        <aside id="rail" aria-label="Evidence">
          <section id="finding" aria-label="Finding">
            <div role="group" aria-label="Actions">
              <button id="select">Select host</button>
              <button id="sibling">Show the configuration</button>
            </div>
          </section>
          <section id="device" aria-label="Device"><button id="dev">Device control</button></section>
        </aside>`;
      const select = document.getElementById("select")!;
      const finding = document.getElementById("finding")!;
      const rail = document.getElementById("rail")!;
      select.focus();
      handOffFocus(select, () => {
        select.remove();
        hide(finding);
      });
      await settle();
      const a = document.activeElement;
      expect(a, `focus went into the pane hidden by ${how}`).not.toBe(document.getElementById("sibling"));
      expect(a).not.toBe(finding);
      expect(a).toBe(rail);
    });
  }
});

describe("the third door keeps the same rule: no candidate a stylesheet hides", () => {
  it("the recorded target sits in a pane a stylesheet hides: passed over for the landmark around the container", () => {
    document.head.innerHTML = `<style>.gone { display: none; }</style>`;
    document.body.innerHTML = `
      <main id="stage" aria-label="Fabric">
        <section id="other" class="gone" aria-label="Other pane"><button id="opener">Open</button></section>
        <div id="drawer"><button id="inside">Finding</button></div>
      </main>`;
    const drawer = document.getElementById("drawer")!;
    const opener = document.getElementById("opener")!;
    document.getElementById("inside")!.focus();
    const landed = releaseFocusFrom(drawer, opener);
    expect(landed, "focus went into a pane the stylesheet hides").not.toBe(opener);
    expect(document.activeElement).toBe(document.getElementById("stage"));
  });
});

describe("rule 4 on the outer walk: a region whose heading cannot take focus is stated by the region itself", () => {
  it("the outer region's labelling heading sits in a hidden part of it: the region, not the next one out", async () => {
    document.body.innerHTML = `
      <main id="page" aria-label="Page">
        <section id="outer" aria-labelledby="outer-title">
          <div id="banner" hidden><h2 id="outer-title">Sources</h2></div>
          <section id="inner" aria-label="Finding">
            <button id="control">Select</button>
          </section>
        </section>
      </main>`;
    const control = document.getElementById("control")!;
    const inner = document.getElementById("inner")!;
    control.focus();
    handOffFocus(control, () => {
      control.remove();
      inner.hidden = true;
    });
    await settle();
    expect(document.activeElement).toBe(document.getElementById("outer"));
  });
});
