/**
 * focus-return.labelledby.test.ts — an `aria-labelledby` list is read the same way on every path.
 *
 * WHAT WAS WRONG (phase 3.5 close-out). `planHandOff`'s walk over the named regions around a control
 * restated `landmarkOf`'s rule instead of reusing it, and the restatement split the IDREF list with
 * `/s+/` — the LETTER s — instead of whitespace. A region labelled by a heading whose id contains an
 * "s" ("sources-title") was then stated as the region itself rather than its heading, so the second
 * door handed focus to a whole region where the first and third doors named its heading. The ids the
 * app happened to use hid it. Each case below is decided by the attribute's value alone: the same
 * layout, labelled by an id with and without the letter, must land on the same element.
 */
import { afterEach, describe, expect, it } from "vitest";
import { handOffFocus, returnFocus } from "./focus-return";

/** An outer region labelled by a heading inside it, around a named inner region holding the control. */
function mount(labelId: string): { control: HTMLButtonElement; inner: HTMLElement; outer: HTMLElement; heading: HTMLElement } {
  document.body.innerHTML = `
    <section id="outer" aria-labelledby="${labelId}">
      <h2 id="${labelId}">Sources</h2>
      <section id="inner" aria-label="Finding">
        <div role="group" aria-label="Actions"><button id="control">Select</button></div>
      </section>
    </section>`;
  return {
    control: document.getElementById("control") as HTMLButtonElement,
    inner: document.getElementById("inner")!,
    outer: document.getElementById("outer")!,
    heading: document.getElementById(labelId)!,
  };
}

/** Let the hand-off's microtask and its first timer run. */
const settle = (): Promise<void> => new Promise((done) => setTimeout(done, 0));

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the second door states an outer region by its labelling heading, whatever the id's letters", () => {
  for (const labelId of ["outer-title", "sources-title", "s", "ids s-and spaces"]) {
    it(`labelled by ${JSON.stringify(labelId)}: focus lands on the heading, not the region`, async () => {
      /* An id with whitespace in it is not one IDREF: the list's first entry is what the attribute names. */
      const first = labelId.split(/\s+/)[0]!;
      const { control, inner, outer, heading } = mount(first);
      outer.setAttribute("aria-labelledby", labelId);
      control.focus();
      expect(document.activeElement).toBe(control);
      /* The action removes the control and hides its whole surface (the nearest named region), so the only
         place left is the named region further out. */
      handOffFocus(control, () => {
        control.remove();
        inner.hidden = true;
      });
      await settle();
      expect(document.activeElement).toBe(heading);
      expect(document.activeElement).not.toBe(outer);
    });
  }

  it("the first door states the same region the same way (the one owner, both paths)", () => {
    const { control, heading } = mount("sources-title");
    const other = document.createElement("button");
    document.body.append(other);
    other.focus();
    /* A context inside the outer region only: its landmark is the outer region, stated by its heading. */
    const context = document.createElement("span");
    heading.after(context);
    expect(returnFocus(null, context)).toBe(heading);
    expect(control.isConnected).toBe(true);
  });
});
