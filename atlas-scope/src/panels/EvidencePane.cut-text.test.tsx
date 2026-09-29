/**
 * EvidencePane.cut-text.test.tsx — a projected text cut to its cap never ends in a citation control for a
 * DIFFERENT record (verifier P3A1-V2-2).
 *
 * The compiler cuts a long member or scalar text at a character count (tools/lib/compile-model.mjs
 * `compileEvidenceRecords`, `cut`). A cut can fall inside a citation, and a truncated pointer can itself be a
 * pointer the model carries — `/config_hygiene/core1/undefined/0/context` cut after `/0` names the row, not the
 * line. `CutText` (./Inspector.tsx, rendered by the one `EvidenceRecordView` the Evidence pane and the Inspector
 * share) shows a cut text only up to its last delimiter. It used to look for that delimiter only in the last 40
 * characters, and to show the text WHOLE when it found none there — so a cut token longer than 40 characters,
 * or a text with no delimiter at all, printed the truncated pointer as a working control for the wrong record.
 *
 * The records are planted in the projected form (the compiler's own shape, checked by `isEvidenceRecord`), with
 * truncated pointers derived from the pointers the compiled model really carries — never a hand-written path.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import type { EvidenceRecord } from "../core/types";
import { citesIn } from "./cited-text";
import { EvidenceRecordView, isEvidenceRecord } from "./Inspector";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});
function render(record: EvidenceRecord): HTMLElement {
  expect(isEvidenceRecord(record), "the planted record has the compiler's shape").toBe(true);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<EvidenceRecordView record={record} onOpenCite={() => {}} />));
  mounted.push({ root, container });
  return container;
}
const citeControls = (c: HTMLElement): string[] =>
  [...c.querySelectorAll("button")].map((b) => b.getAttribute("aria-label") ?? "").filter((l) => l.startsWith("Open source record ")).map((l) => l.slice("Open source record ".length));

/** A carried pointer `whole` with a strict prefix `cut` (at a "/") that is itself a carried, citable pointer. */
const pair = (() => {
  const carried = (fabric.evidenceRecords ?? []).map((r) => r.pointer);
  const set = new Set(carried);
  for (const whole of carried) {
    for (let at = whole.lastIndexOf("/"); at > 0; at = whole.lastIndexOf("/", at - 1)) {
      const cut = whole.slice(0, at);
      if (set.has(cut) && citesIn(cut).length === 1) return { whole, cut };
    }
  }
  return null;
})();

const scalar = (value: string, wholeLength: number): EvidenceRecord => ({
  pointer: "/planted/cut-text",
  cite: "/planted/cut-text",
  type: "string",
  jsonChars: wholeLength + 2,
  value,
  nested: [],
  cut: { "": wholeLength },
  fieldsTotal: 0,
  withheld: false,
});

describe("a cut text never ends in a control for a different record", () => {
  it("precondition: the model carries a pointer whose truncation is another carried pointer", () => {
    expect(pair, "a carried pointer with a carried, citable prefix").not.toBeNull();
    // And that prefix, printed, IS a working citation — which is exactly why a cut must not print it.
    expect(citesIn(`see ${pair!.cut}`)).toEqual([pair!.cut]);
  });

  it("uncut, the same text shows its citation as a control (so the cases below are not vacuous)", () => {
    const text = `The engine cites ${pair!.cut}`;
    const c = render(scalar(text, text.length));
    expect(citeControls(c)).toEqual([pair!.cut]);
  });

  it("a cut inside a pointer, after a delimiter within the last 40 characters: the fragment is not shown", () => {
    const text = `The engine cites ${pair!.cut}`;
    const whole = text.length + (pair!.whole.length - pair!.cut.length);
    const c = render(scalar(text, whole));
    expect(citeControls(c), "no control for the truncated pointer").toEqual([]);
    const shown = "The engine cites ";
    expect(c.textContent ?? "").toContain(`(the first ${shown.length} of ${whole} characters)`);
  });

  it("a cut token LONGER than 40 characters after the last delimiter is still not shown", () => {
    // The token after the last delimiter ('"') runs 11 + the pointer's length characters: past a 40-character window.
    const lead = `a "${"z".repeat(10)}(`;
    const text = `${lead}${pair!.cut}`;
    expect(text.length - text.lastIndexOf('"') - 1, "precondition: the cut token is longer than 40 characters").toBeGreaterThan(40);
    const whole = text.length + (pair!.whole.length - pair!.cut.length);
    const c = render(scalar(text, whole));
    expect(citeControls(c), "no control for the truncated pointer").toEqual([]);
    expect(c.textContent ?? "").not.toContain(pair!.cut);
    expect(c.textContent ?? "").toContain(`(the first 3 of ${whole} characters)`);
  });

  it("a cut text with no delimiter at all shows none of the cut token, and says so", () => {
    const text = pair!.cut;
    const whole = pair!.whole.length;
    const c = render(scalar(text, whole));
    expect(citeControls(c), "no control for the truncated pointer").toEqual([]);
    expect(c.textContent ?? "").not.toContain(pair!.cut);
    expect(c.textContent ?? "").toMatch(new RegExp(`the first 0 of ${whole} characters`));
    expect(c.textContent ?? "").toMatch(/inside one unbroken token/);
  });

  it("a cut MEMBER of a record is held to the same rule as a cut scalar", () => {
    const text = `x "${"z".repeat(10)}(${pair!.cut}`;
    const whole = text.length + 9;
    const record: EvidenceRecord = {
      pointer: "/planted/cut-member",
      cite: "/planted/cut-member",
      type: "object",
      jsonChars: whole + 20,
      value: { detail: text },
      nested: [],
      cut: { detail: whole },
      fieldsTotal: 1,
      withheld: false,
    };
    const c = render(record);
    expect(citeControls(c)).toEqual([]);
    expect(c.textContent ?? "").toContain(`(the first 3 of ${whole} characters)`);
  });
});
