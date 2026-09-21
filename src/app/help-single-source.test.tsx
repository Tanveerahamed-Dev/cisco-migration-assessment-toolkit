/**
 * help-single-source.test.tsx — there is ONE keyboard reference, and it is generated.
 *
 * Two agents independently built a help overlay, and both were reasoning correctly from where they
 * stood:
 *   - `src/app/ShortcutHelp.tsx` renders `useShortcuts()`, the live registry. It lists whatever is
 *     actually bound, so it cannot rot.
 *   - a second overlay, private to `Header.tsx`, rendered a hand-written `OWN_SHORTCUTS` array,
 *     on the stated principle that "a keyboard reference that lists a shortcut nobody wired is a
 *     false claim about the product, made in the one place a user goes when they are already
 *     stuck." That is exactly right — and it was written because Header installs its bindings with
 *     a raw `window.addEventListener`, so they never reach the registry and the generated sheet
 *     could not see them.
 *
 * Each was a reasonable local answer; together they are a defect. Pressing `?` ran two handlers,
 * and one of the two lists was maintained by hand — the thing design-brief 7.1 explicitly forbids.
 *
 * The fix is to remove the CAUSE rather than one of the symptoms: Header registers its bindings
 * with the manager, so the generated sheet lists them and the second overlay has no reason to
 * exist. These tests pin that, and would fail again if either overlay came back.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { Header } from "./Header";
import { ShortcutHelp } from "./ShortcutHelp";
import { shortcuts } from "./keyboard";
import { useAppCommands } from "./commands";

/* Same mount helper the sibling suites use: this project renders with react-dom/client directly
   rather than adding a testing library, so the tests exercise the real mount path. */
const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

/**
 * Dispatch on `document`, not `window`.
 *
 * `keyboard.ts` installs its single listener with `document.addEventListener("keydown", …)`. An
 * event dispatched on `window` fires only window's own listeners — it does not travel down to
 * document — so a harness that dispatches there silently exercises nothing and every key assertion
 * fails for a reason that has nothing to do with the product. (That asymmetry is also why the
 * removed raw `window.addEventListener` in Header appeared to work in its own test while a
 * registered binding did not.)
 */
const press = (key: string): void => {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
};

/**
 * Mirror what `App.tsx` actually mounts.
 *
 * An earlier version of this harness rendered only `<Header/>` and `<ShortcutHelp/>` and every
 * assertion failed — not because the product was wrong but because `useAppCommands()` was missing,
 * so the registry held Header's binding and nothing else. That is the fixture trap in miniature:
 * the test would have been reporting on an application nobody ships.
 */
function Harness(): ReactNode {
  useAppCommands();
  return (
    <>
      <Header />
      <ShortcutHelp />
    </>
  );
}

function mountApp(): void {
  mount(<Harness />);
}

describe("the keyboard reference has a single source", () => {
  it("opens exactly ONE overlay when ? is pressed", () => {
    mountApp();
    press("?");
    // Both implementations are counted: the generated sheet uses `.kb-help`, the removed
    // Header-private one used `.kbdhelp`. Seeing either twice, or seeing both, is the defect.
    const generated = document.querySelectorAll(".kb-help").length;
    const headerPrivate = document.querySelectorAll(".kbdhelp").length;
    expect(
      { generated, headerPrivate },
      "pressing ? must open one keyboard reference, not two",
    ).toEqual({ generated: 1, headerPrivate: 0 });
  });

  it("registers Header's own bindings, so the generated sheet can list them", () => {
    mountApp();
    const ids = shortcuts().map((s) => s.id);
    /* `/` is Header's own binding and was installed with a raw `window.addEventListener`, so the
       generated sheet could not see it. A help screen that omits a real shortcut is the same class
       of lie as one that invents a fake one, and it fails at the exact moment a user consults it.
       (`view.theme` is registered by commands.ts and is asserted here only as the control: it
       proves this test reads a populated registry rather than an empty one.) */
    expect(ids, "view.theme should already be registered — if this fails the registry is empty and the assertion below proves nothing").toContain("view.theme");
    expect(ids, "query.focus is not in the registry; Header is still binding / privately").toContain("query.focus");
  });

  it("lists Header's bindings in the rendered sheet, not merely in the registry", () => {
    mountApp();
    press("?");
    const sheet = document.querySelector(".kb-help");
    expect(sheet).not.toBeNull();
    const text = sheet?.textContent ?? "";
    expect(text).toMatch(/query bar/i);
  });

  /*
   * Where `/` actually LANDS is an App-level property, not one this file can honestly assert.
   * `commands.ts` declares `query.focus` as a capability and `App.tsx` registers the query input as
   * its target; a harness that renders Header without App has the capability but no target, so the
   * key resolves somewhere else. Asserting it here would be testing the harness.
   *
   * Verified in the real application instead, with Playwright against the running app:
   *     after '?': {"generated":1,"headerPrivate":0}
   *     after '/': {"tag":"input","type":"text","inQueryBar":true}
   *     pageerrors: 0
   *
   * What this file CAN prove is the change that was made here: Header no longer binds `/` itself.
   */
  it("Header does not bind / itself — the capability owns it", async () => {
    const src = await import("node:fs").then((fs) => fs.readFileSync("src/app/Header.tsx", "utf8"));
    expect(
      /e\.key === "\/"/.test(src),
      "Header.tsx handles / again; `query.focus` in commands.ts already owns that key",
    ).toBe(false);
    // And the capability that does own it is registered, with exactly one entry.
    mountApp();
    const slash = shortcuts().filter((s) => s.keys === "/");
    expect(slash.map((s) => s.id), "exactly one binding may claim /").toEqual(["query.focus"]);
  });

  it("every registered shortcut carries a label, so none renders blank on the sheet", () => {
    mountApp();
    const blank = shortcuts().filter((s) => (s.label ?? "").trim() === "");
    expect(blank.map((s) => s.id), "registered shortcuts with no label").toEqual([]);
  });

  it("no two registered shortcuts share a spec within the same scope", () => {
    mountApp();
    const seen = new Map<string, string>();
    const clashes: string[] = [];
    for (const s of shortcuts()) {
      const key = `${s.scope}:${s.keys}`;
      const prior = seen.get(key);
      if (prior !== undefined) clashes.push(`${key} bound by both ${prior} and ${s.id}`);
      else seen.set(key, s.id);
    }
    expect(clashes, ["two bindings claim the same key in the same scope:", ...clashes].join(" | ")).toEqual([]);
  });
});

/** Guards the structural cause, not just today's symptom. */
describe("the cause stays fixed", () => {
  it("Header does not render a private help overlay", async () => {
    const src = await import("node:fs").then((fs) => fs.readFileSync("src/app/Header.tsx", "utf8"));
    expect(
      /function\s+ShortcutHelp\s*\(/.test(src),
      "Header.tsx defines its own ShortcutHelp again — the generated sheet is the single source",
    ).toBe(false);
  });

  it("Header does not hand-maintain a shortcut list", async () => {
    const src = await import("node:fs").then((fs) => fs.readFileSync("src/app/Header.tsx", "utf8"));
    // A literal array of {keys, action} pairs is the shape that rots. Bindings registered with the
    // manager carry a `run`, so they cannot be listed without also being wired.
    expect(
      /keys:\s*"[^"]+",\s*action:/.test(src),
      "Header.tsx carries a hand-written keys/action list again (design brief 7.1)",
    ).toBe(false);
  });
});
