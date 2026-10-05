/**
 * drawer-focus-return.test.tsx — acceptance D3 for the container that CLOSES AROUND focus: the
 * evidence drawer (Rail B at the drawer rung, 1024–1279 px, design brief 2.5).
 *
 * MEASURED (acceptance report, D3 overturned PASS -> FAIL): at 1100, 1024 and 1270 px, with focus on
 * the drawer's "Finding" radio, `e` closed the drawer and ~250 ms later — when the CSS `visibility`
 * step lands — Chromium parked focus on <body>; the palette's "Toggle the evidence rail" did the same,
 * and Escape did not close the drawer at all. Also measured by the discovery pass: resizing 1100 ->
 * 900 with focus inside the open drawer ended on <body>, and `g e` with the drawer closed announced
 * "Moved to the evidence rail." while focus never moved.
 *
 * JSDOM DOES NO FOCUS FIX-UP, so "focus is not on <body>" would pass vacuously here: the radio keeps
 * focus even after its rail is hidden. What IS decidable here, and what these cases assert, is that
 * focus has LEFT the container that closed — `#rail-evidence` — and gone to the element the owner
 * (`src/app/focus-return.ts`, `releaseFocusFrom`) chose: the control that opened the drawer, or, when
 * that is gone, the documented fallback chain. The real browser, with the real 240 ms visibility step,
 * is `node review/audit-d3-focus.mjs --sweep` (its drawer pass: every opener x every close path x
 * every drawer width derived from LADDER_REM, plus a resize to a width of every other rung).
 *
 * No module is mocked: the real frame is mounted (the stage's lazy chunk is preloaded while this file
 * is collected, as composite-tabstop.test.tsx does, so every case mounts the same frame).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { flushTurns } from "../test-support/act-turns";
import { App } from "./App";
import { goToSurface } from "./commands";
import { releaseFocusFrom, recordReturn } from "./focus-return";
import "../fabric3d/Fabric3D";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ── harness ─────────────────────────────────────────────────────────────── */

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<App />));
  mounted.push({ root, container });
  return container;
}

/** The viewport, as the ladder's rem media queries see it. Mutable, so a case can resize. */
let width = 1100;
const realMatchMedia = window.matchMedia;
function answerMedia(): void {
  window.matchMedia = ((q: string) => {
    let matches = true;
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)(rem|px)\)/g)) {
      const bound = Number.parseFloat(m[2] as string) * (m[3] === "px" ? 1 : 16);
      matches &&= m[1] === "min" ? width >= bound : width <= bound;
    }
    if (/prefers-reduced-motion/.test(q)) matches = false;
    return {
      matches,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;
}
/** Resize: the ladder re-reads on `resize` (surfaces.tsx useAtLeast). */
function resizeTo(w: number): void {
  width = w;
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

/** Eight act turns of 20 ms each, through the shared helper (never a raw async act() scope). */
const settle = (): Promise<void> => flushTurns(20, 8);

/** A real keydown on the focused element (bubbling to the document's keyboard manager). */
const press = (key: string, init: KeyboardEventInit = {}): void => {
  const target = document.activeElement ?? document.body;
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
  });
};
const MOD: KeyboardEventInit = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent) ? { metaKey: true } : { ctrlKey: true };

const app = (): HTMLElement => document.querySelector<HTMLElement>(".app")!;
const rail = (): HTMLElement => document.getElementById("rail-evidence")!;
const drawerOpen = (): boolean => app().getAttribute("data-drawer") === "open";
const inRail = (): boolean => rail().contains(document.activeElement);
const gridCell = (): HTMLElement => {
  const c = document.querySelector<HTMLElement>('#rail-queue [role="grid"] [tabindex="0"]');
  expect(c, "the findings grid rendered no roving cell to start from").not.toBeNull();
  return c!;
};
/** A tab stop INSIDE the drawer — the Finding/Device radio holding the group's tab stop. */
const insideStop = (): HTMLElement => {
  const r = rail().querySelector<HTMLElement>('[role="radio"][tabindex="0"]');
  expect(r, "the evidence rail rendered no radio to put focus on").not.toBeNull();
  return r!;
};
const status = (): string => (document.getElementById("sr-status")?.textContent ?? "").replace(/​/g, "");

/** Open the drawer with `e` from the grid cell, then put focus inside it. Returns the opener. */
async function openWithEAndEnter(): Promise<HTMLElement> {
  const cell = gridCell();
  act(() => cell.focus());
  press("e");
  await settle();
  expect(drawerOpen(), "precondition: `e` at the drawer rung opens the drawer").toBe(true);
  expect(document.activeElement, "precondition: opening leaves focus on the opener").toBe(cell);
  act(() => insideStop().focus());
  expect(inRail(), "precondition: focus is inside the open drawer").toBe(true);
  return cell;
}

const finding = fabric.findings[0]!;

beforeEach(async () => {
  width = 1100;
  answerMedia();
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });
  act(() => {
    useInvestigation.getState().selectFinding(finding.id);
    useInvestigation.getState().setSurface("findings");
  });
  mount();
  await settle();
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });
});

/* ── the three keyboard close paths ───────────────────────────────────────── */

describe("closing the evidence drawer from inside returns focus to the control that opened it (1100 px)", () => {
  it("`e` from inside: the drawer closes and focus is back on the grid cell, not inside the rail", async () => {
    const opener = await openWithEAndEnter();
    press("e");
    await settle();
    expect(drawerOpen()).toBe(false);
    expect(inRail(), "focus was left inside the drawer that just closed (Chromium parks it on <body> 240 ms later)").toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("Escape from inside closes the drawer (owner decision, design brief 7.1) and returns focus", async () => {
    const opener = await openWithEAndEnter();
    press("Escape");
    await settle();
    expect(drawerOpen(), "Escape with focus inside the drawer did not close it").toBe(false);
    expect(inRail()).toBe(false);
    expect(document.activeElement).toBe(opener);
    expect(status()).toMatch(/Evidence drawer closed/);
  });

  it("the palette's 'Toggle the evidence rail', run from inside, returns focus to the drawer's opener", async () => {
    const opener = await openWithEAndEnter();
    press("k", MOD);
    await settle();
    const input = document.querySelector<HTMLInputElement>('[role="dialog"] input[role="combobox"]');
    expect(input, "the palette did not open").not.toBeNull();
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(input, "Toggle the evidence rail");
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await settle();
    const active = document.getElementById(input!.getAttribute("aria-activedescendant") ?? "");
    expect(active?.textContent ?? "", "the palette's top row is not the evidence toggle").toMatch(/Toggle the evidence rail/);
    act(() => {
      input!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    });
    await settle();
    expect(drawerOpen()).toBe(false);
    expect(inRail()).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("an inner layer closes first: Escape in the configuration overlay closes the overlay, the next Escape the drawer", async () => {
    const cell = gridCell();
    act(() => cell.focus());
    press("v");
    await settle();
    expect(drawerOpen(), "precondition: `v` at the drawer rung opens the drawer").toBe(true);
    const overlay = (): Element | null => rail().querySelector(".ev-cfg");
    expect(overlay(), `precondition: ${finding.id} opens a configuration overlay (the audit measured one on this finding)`).not.toBeNull();
    expect(inRail(), "precondition: `v` put focus inside the drawer").toBe(true);
    press("Escape");
    await settle();
    expect(overlay(), "the first Escape did not close the inner overlay").toBeNull();
    expect(drawerOpen(), "the first Escape closed the drawer around an open inner layer").toBe(true);
    expect(inRail()).toBe(true);
    press("Escape");
    await settle();
    expect(drawerOpen(), "the second Escape did not close the drawer").toBe(false);
    expect(document.activeElement).toBe(cell);
  });

  it("Escape with focus OUTSIDE the drawer leaves it open (it closes the layer that holds focus)", async () => {
    await openWithEAndEnter();
    const stage = document.getElementById("stage")!;
    act(() => stage.focus());
    press("Escape");
    await settle();
    expect(drawerOpen()).toBe(true);
    expect(document.activeElement).toBe(stage);
  });
});

/* ── closed means unreachable at once, not 240 ms later (verifier D3-V1) ─────── */

describe("a closing drawer cannot be re-entered during its closing slide", () => {
  /* MEASURED (independent verifier, release build, 1100 px): open with `e`, close with `e`, then seven
     Tab presses at Playwright speed — focus walked back INTO the rail, which was still `visibility:
     visible` for its 240 ms slide, and sat on its "Finding" radio; 600 ms later it was on <body>.
     The same happened to a programmatic focus() and, in the audit's default run at 1152 px, to the
     next case's tab.focus(). The release ran once, on the shown -> hidden commit; nothing stopped
     focus coming back in afterwards. jsdom neither lays out nor honours `inert` for focus(), so
     what is asserted is the owner's act — the rail is `inert` from the very commit that closes it
     (Chromium then skips it for Tab and refuses focus() into it) — and that it is lifted on reopen. */
  it("`e` from inside: the rail is inert in the same commit that closes it, and reopening lifts it", async () => {
    const opener = await openWithEAndEnter();
    expect(rail().hasAttribute("inert"), "the OPEN drawer is inert: nothing in it could be reached").toBe(false);
    press("e");
    expect(rail().hasAttribute("inert"), "the closing drawer is still reachable during its slide (Tab walks back into it)").toBe(true);
    expect(document.activeElement).toBe(opener);
    await settle();
    press("e");
    await settle();
    expect(drawerOpen()).toBe(true);
    expect(rail().hasAttribute("inert"), "reopening left the drawer inert").toBe(false);
  });

  it("Escape from inside: the same — inert at once", async () => {
    await openWithEAndEnter();
    press("Escape");
    expect(drawerOpen()).toBe(false);
    expect(rail().hasAttribute("inert"), "the drawer closed by Escape is still reachable during its slide").toBe(true);
  });

  it("a drawer that was never opened is inert at the drawer rung, and the persistent rail at 1440 px never is", async () => {
    expect(drawerOpen()).toBe(false);
    expect(rail().hasAttribute("inert"), "the closed drawer at mount can be tabbed into").toBe(true);
    resizeTo(1440);
    await settle();
    expect(rail().hidden).toBe(false);
    expect(rail().hasAttribute("inert"), "the persistent rail was left inert").toBe(false);
  });
});

/* ── the opener gone: the documented fallback chain, never inside the rail ── */

describe("when the opener is gone, focus follows the fallback chain", () => {
  it("the drawer's opener removed while it was open: focus goes to the stage, not into the closed rail", async () => {
    const temp = document.createElement("button");
    temp.textContent = "temporary opener";
    document.body.appendChild(temp);
    act(() => temp.focus());
    press("e");
    await settle();
    expect(drawerOpen()).toBe(true);
    act(() => insideStop().focus());
    temp.remove();
    press("e");
    await settle();
    expect(drawerOpen()).toBe(false);
    expect(inRail()).toBe(false);
    expect(document.activeElement).toBe(document.getElementById("stage"));
  });
});

/* ── a layout change while the drawer holds focus ─────────────────────────── */

describe("a resize out of the drawer rung while the drawer holds focus", () => {
  it("1100 -> 900 (the rail is hidden at the single-column rung): focus leaves the rail; back at 1100 the drawer is closed", async () => {
    const opener = await openWithEAndEnter();
    resizeTo(900);
    await settle();
    expect(rail().hidden, "precondition: at 900 px on the queue pane Rail B is hidden").toBe(true);
    expect(inRail(), "focus was left inside the rail the resize hid").toBe(false);
    expect(document.activeElement).toBe(opener);
    resizeTo(1100);
    await settle();
    expect(drawerOpen(), "the drawer's open state survived leaving its rung and reopened it on return").toBe(false);
    expect(useInvestigation.getState().evidenceDrawerOpen).toBe(false);
  });

  it("1100 -> 390 (every rail is a stacked section): focus stays on its control, and the layout change brings it into view", async () => {
    /* MEASURED (review/audit-d3-focus.mjs drawer pass, pre-fix build, 1152 -> 390): focus stayed on
       the "Finding" radio, now in the stacked rail far below the fold — "no part of it is on screen".
       jsdom lays nothing out, so what is asserted is the owner's act: the focused control is scrolled
       into view by the layout change. */
    await openWithEAndEnter();
    const focused = document.activeElement as HTMLElement;
    const calls: Element[] = [];
    const real = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element): void {
      calls.push(this);
    };
    try {
      resizeTo(390);
      await settle();
    } finally {
      Element.prototype.scrollIntoView = real;
    }
    expect(rail().hidden, "precondition: at 390 px Rail B is a stacked section, shown").toBe(false);
    expect(document.activeElement, "focus moved although its rail is still shown").toBe(focused);
    expect(calls, "the layout change left the focused control wherever the new layout put it").toContain(focused);
  });
});

/* ── g e: open first, and announce only a move that happened ──────────────── */

describe("`g e` at the drawer rung", () => {
  it("opens the drawer before moving focus into it, and Escape then returns to where the reader was", async () => {
    const cell = gridCell();
    act(() => cell.focus());
    press("g");
    press("e");
    await settle();
    expect(drawerOpen(), "`g e` moved to a rail that is closed").toBe(true);
    expect(inRail()).toBe(true);
    expect(status()).toMatch(/Moved to the evidence rail/);
    press("Escape");
    await settle();
    expect(drawerOpen()).toBe(false);
    expect(document.activeElement).toBe(cell);
  });

  it("does not announce a move when focus did not land", async () => {
    const cell = gridCell();
    act(() => cell.focus());
    /* A landing that refuses focus, as a control in a hidden or inert region does in a browser. */
    const landing = rail().querySelector<HTMLElement>("button")!;
    const refuse = (): void => {};
    Object.defineProperty(landing, "focus", { value: refuse, configurable: true });
    act(() => goToSurface("evidence"));
    await settle();
    expect(document.activeElement).toBe(cell);
    expect(status(), "announced a move that did not happen").not.toMatch(/^Moved to/);
    expect(status()).toMatch(/evidence rail/);
  });
});

/* ── the owner's door, on plain DOM ───────────────────────────────────────── */

describe("releaseFocusFrom — the owner's door for a container that hides while holding focus", () => {
  const build = (): { box: HTMLElement; inner: HTMLButtonElement; outside: HTMLButtonElement; later: HTMLButtonElement } => {
    document.body.innerHTML = "";
    const outside = document.createElement("button");
    outside.textContent = "outside";
    const box = document.createElement("aside");
    box.setAttribute("aria-label", "Box");
    const inner = document.createElement("button");
    inner.textContent = "inner";
    box.appendChild(inner);
    const later = document.createElement("button");
    later.textContent = "after the box";
    document.body.append(outside, box, later);
    return { box, inner, outside, later };
  };

  it("does nothing when focus is not inside the container", () => {
    const { box, outside } = build();
    outside.focus();
    expect(releaseFocusFrom(box, null, [])).toBeNull();
    expect(document.activeElement).toBe(outside);
  });

  it("returns to the recorded target when it lies outside", () => {
    const { box, inner, outside } = build();
    const record = recordReturn(outside, box);
    inner.focus();
    expect(releaseFocusFrom(box, record, [])).toBe(outside);
    expect(document.activeElement).toBe(outside);
  });

  it("skips every candidate inside the container (it is still 'visible' for its closing transition)", () => {
    const { box, inner, later } = build();
    const second = document.createElement("button");
    box.appendChild(second);
    inner.focus();
    expect(releaseFocusFrom(box, second, [inner, later])).toBe(later);
  });

  it("skips a fallback inside a hidden subtree", () => {
    const { box, inner, later } = build();
    const hiddenWrap = document.createElement("div");
    hiddenWrap.hidden = true;
    const hiddenBtn = document.createElement("button");
    hiddenWrap.appendChild(hiddenBtn);
    document.body.appendChild(hiddenWrap);
    inner.focus();
    expect(releaseFocusFrom(box, null, [hiddenBtn, later])).toBe(later);
  });

  it("with no target, opener or fallback left, takes the nearest tab stop outside the container — never stays inside", () => {
    const { box, inner, later } = build();
    inner.focus();
    const got = releaseFocusFrom(box, null, []);
    expect(got).not.toBeNull();
    expect(box.contains(document.activeElement)).toBe(false);
    expect(document.activeElement).not.toBe(document.body);
    expect(got).toBe(later);
  });
});
