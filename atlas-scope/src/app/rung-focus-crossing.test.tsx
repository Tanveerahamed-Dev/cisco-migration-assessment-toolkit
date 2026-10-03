/**
 * rung-focus-crossing.test.tsx — acceptance D3 for the class the independent verifier named D3-R2-1:
 * a control or panel that UNMOUNTS (or stops being rendered) on a rung crossing or a resize while it
 * holds focus. The drawer was one instance of it; these are the others it measured on a release build
 * (74 tab stops across 7 rung crossings, 11 lost to <body>):
 *
 *   'LOST 900->1100 stop 33: BUTTON.paneswitch__btn "Queue" -> BODY'
 *   '900 focus More → 900->1100 (More unmounted) BODY'
 *   'inside More popover (thm__opt) → 900->1100 BODY'
 *   '1100 focus "Copy the link…" → 1100->900 BODY'
 *   'LOST 1100->1440 stop 13: BUTTON.ui-btn "View" -> BODY'
 *   'LOST 768->390 stop 17: BUTTON.fabric3d__btn "Legend" -> BODY'
 *
 * Each case below is one of those shapes, driven through the real frame at the real ladder widths
 * (the rem media queries are answered from a mutable width, and `resize` is what the ladder re-reads).
 * The rule under test is focus-return.ts's FOURTH DOOR (`useReleaseFocusOnLayoutChange`): the element
 * that held focus is gone after the layout commit, so focus goes to its documented successor — its
 * TWIN in the new layout (same role, same accessible name), else the successor its surface states in
 * `data-focus-successor`, else the caller's fallbacks — and never to <body>.
 *
 * JSDOM REMOVES FOCUS ON UNMOUNT (activeElement becomes <body>), so an unmount case here is a real
 * test of the loss. It does NOT apply stylesheets, so the CSS-only hides (the stage's `display: none`
 * below 768 px, which took the fabric's "Legend" away) and the measured View fold (a ResizeObserver
 * over real layout) cannot happen here; the hook's contract for a hide is proved in isolation below,
 * and the browser proof for every focusable element at every rung crossing is
 * `node review/audit-d3-focus.mjs --sweep` (its rung-crossing pass).
 */
import { act, useRef, useState, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useInvestigation } from "../core/store";
import { flushTurns } from "../test-support/act-turns";
import { App } from "./App";
import { useReleaseFocusOnLayoutChange } from "./focus-return";
import "../fabric3d/Fabric3D";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ── harness ─────────────────────────────────────────────────────────────── */

const mounted: { root: Root; container: HTMLElement }[] = [];

function mountNode(node: ReactElement): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(node);
  });
  mounted.push({ root, container });
  return container;
}

let width = 900;
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
function resizeTo(w: number): void {
  width = w;
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}
const settle = (): Promise<void> => flushTurns(20, 8);

async function mountAppAt(w: number): Promise<void> {
  width = w;
  answerMedia();
  mountNode(<App />);
  await settle();
}

const focusOn = (el: HTMLElement | null, what: string): HTMLElement => {
  expect(el, `precondition: ${what} is rendered`).not.toBeNull();
  act(() => {
    el!.focus();
  });
  expect(document.activeElement, `precondition: focus is on ${what}`).toBe(el);
  return el!;
};
const active = (): Element | null => document.activeElement;
/** Where focus is, in words, for a failure message. */
const where = (): string => {
  const a = document.activeElement;
  if (a === null || a === document.body) return "BODY";
  return `${a.tagName}${a.id ? `#${a.id}` : ""}.${(a as HTMLElement).className} "${(a.getAttribute("aria-label") ?? a.textContent ?? "").trim().slice(0, 40)}"`;
};
const expectNotLost = (why: string): void => {
  const a = active();
  expect(a !== null && a !== document.body && a.isConnected, `${why}: focus was dropped (${where()})`).toBe(true);
};

beforeEach(() => {
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => {
      m.root.unmount();
    });
    m.container.remove();
  }
  document.body.innerHTML = "";
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });
});

/* ── the pane switch (App.tsx mounts it only below 1024 px) ─────────────────── */

describe("the pane switch unmounts on a rung crossing: focus goes to the pane it chose, never <body>", () => {
  it("900 -> 1100 with focus on 'Queue': lands in the queue region it stood for", async () => {
    await mountAppAt(900);
    focusOn(document.querySelector<HTMLElement>('.paneswitch__btn[data-pane-id="queue"]'), "the Queue radio");
    resizeTo(1100);
    await settle();
    expect(document.querySelector(".paneswitch"), "precondition: the pane switch is gone at the drawer rung").toBeNull();
    expectNotLost("900 -> 1100 from the Queue radio");
    expect(document.getElementById("rail-queue")!.contains(active()), `focus is not in the queue region (${where()})`).toBe(true);
  });

  it("900 -> 1100 with focus on 'Evidence': the evidence drawer is closed there, so the stage (its stated next successor)", async () => {
    act(() => {
      useInvestigation.getState().setSurface("evidence");
    });
    await mountAppAt(900);
    focusOn(document.querySelector<HTMLElement>('.paneswitch__btn[data-pane-id="evidence"]'), "the Evidence radio");
    resizeTo(1100);
    await settle();
    expectNotLost("900 -> 1100 from the Evidence radio");
    expect(document.getElementById("rail-evidence")!.contains(active()), "focus went into the closed (inert) drawer").toBe(false);
    expect(active()).toBe(document.getElementById("stage"));
  });

  it("900 -> 390 with focus on 'Queue': the radios leave (every rail is stacked), focus lands in the queue region", async () => {
    await mountAppAt(900);
    focusOn(document.querySelector<HTMLElement>('.paneswitch__btn[data-pane-id="queue"]'), "the Queue radio");
    resizeTo(390);
    await settle();
    expect(document.querySelector(".paneswitch__group"), "precondition: the radios are gone at the stacked rung").toBeNull();
    expectNotLost("900 -> 390 from the Queue radio");
    expect(document.getElementById("rail-queue")!.contains(active()), `focus is not in the queue region (${where()})`).toBe(true);
  });

  it("390 -> 900 with focus on the fabric toggle: the toggle leaves, focus lands on the stage it stood for", async () => {
    await mountAppAt(390);
    focusOn(document.querySelector<HTMLElement>(".paneswitch__fabric"), "the fabric toggle");
    resizeTo(900);
    await settle();
    expect(document.querySelector(".paneswitch__fabric"), "precondition: the toggle is gone above the stacked rung").toBeNull();
    expectNotLost("390 -> 900 from the fabric toggle");
    expect(active()).toBe(document.getElementById("stage"));
  });
});

/* ── the header's compact rung (More popover <-> inline toolbar) ──────────────── */

describe("the header's More popover and its inline toolbar swap on a rung crossing: focus follows to the same control", () => {
  it("900 -> 1100 with focus on More: lands on the inline surface toolbar that took its place", async () => {
    await mountAppAt(900);
    focusOn(document.querySelector<HTMLElement>("button.hdr-more"), "the More button");
    resizeTo(1100);
    await settle();
    expect(document.querySelector("button.hdr-more"), "precondition: More is gone at the drawer rung").toBeNull();
    expectNotLost("900 -> 1100 from More");
    expect(document.querySelector(".hdr-surfaces")!.contains(active()), `focus is not on the inline surface toolbar (${where()})`).toBe(true);
  });

  it("900 -> 1100 with focus INSIDE the open More popover: lands on the same control in the inline header", async () => {
    await mountAppAt(900);
    const more = document.querySelector<HTMLElement>("button.hdr-more")!;
    act(() => {
      more.click();
    });
    await settle();
    const inside = [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-label="More controls"] button')].find(
      (b) => (b.textContent ?? "").trim() === "Copy the link to this investigation",
    );
    focusOn(inside ?? null, "the popover's Copy-link button");
    resizeTo(1100);
    await settle();
    expectNotLost("900 -> 1100 from inside More");
    expect(active()?.getAttribute("aria-label"), `focus is not on the inline twin (${where()})`).toBe("Copy the link to this investigation");
    expect(document.getElementById("app-header")!.contains(active())).toBe(true);
  });

  it("1100 -> 900 with focus on the inline Copy-link button: it moves into the popover, so focus lands on More", async () => {
    await mountAppAt(1100);
    focusOn(document.querySelector<HTMLElement>('#app-header button[aria-label="Copy the link to this investigation"]'), "the inline Copy-link button");
    resizeTo(900);
    await settle();
    expectNotLost("1100 -> 900 from the inline Copy-link button");
    expect(active()).toBe(document.querySelector("button.hdr-more"));
  });

  it("1100 -> 900 with focus on an inline surface button: focus lands on More, which now carries it", async () => {
    await mountAppAt(1100);
    const findings = [...document.querySelectorAll<HTMLElement>(".hdr-surfaces button")].find((b) => (b.textContent ?? "").startsWith("Findings"));
    focusOn(findings ?? null, "the inline Findings button");
    resizeTo(900);
    await settle();
    expectNotLost("1100 -> 900 from the inline Findings button");
    expect(active()).toBe(document.querySelector("button.hdr-more"));
  });
});

/* ── an edge no JavaScript layout names (the stylesheet-only wide refinement) ──── */

describe("a crossing at an edge only the stylesheet re-flows at still keeps surviving focus in view", () => {
  it("1700 -> 1500 (the 100rem wide edge): the focused evidence control is scrolled into view", async () => {
    /* MEASURED (review/audit-d3-focus.mjs rung-crossing pass, release build): at 1920 -> 1440 px the
       focused "Show the configuration" in the evidence rail survived the re-flow outside its scroller
       ("no part of it is on screen") — `useLadder` names no rung change at 1600 px, so nothing ran.
       jsdom lays nothing out; what is asserted is the frame's act: the crossing scrolls the element
       holding focus into view, as it does at every other edge. */
    act(() => {
      useInvestigation.getState().setSurface("evidence");
    });
    await mountAppAt(1700);
    const radio = focusOn(document.querySelector<HTMLElement>('#rail-evidence [role="radio"][tabindex="0"]'), "the evidence rail's radio");
    const calls: Element[] = [];
    const real = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element): void {
      calls.push(this);
    };
    try {
      resizeTo(1500);
      await settle();
    } finally {
      Element.prototype.scrollIntoView = real;
    }
    expect(active()).toBe(radio);
    expect(calls, "the crossing at the wide edge did not bring the focused control into view").toContain(radio);
  });
});

/* ── what the door must NOT do ─────────────────────────────────────────────── */

describe("the layout door moves focus only when the crossing took it", () => {
  it("focus on a control that survives the crossing stays exactly where it is", async () => {
    await mountAppAt(900);
    const field = focusOn(document.querySelector<HTMLElement>('#app-header form[role="search"] input'), "the query field");
    resizeTo(1100);
    await settle();
    expect(active()).toBe(field);
    resizeTo(390);
    await settle();
    expect(active()).toBe(field);
  });

  it("focus the reader put on <body> (a pointer press on nothing) is not pulled back to a successor", async () => {
    await mountAppAt(900);
    const radio = focusOn(document.querySelector<HTMLElement>('.paneswitch__btn[data-pane-id="queue"]'), "the Queue radio");
    act(() => {
      document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
      radio.blur();
    });
    expect(active(), "precondition: focus is on <body> by the reader's own press").toBe(document.body);
    resizeTo(1100);
    await settle();
    expect(active(), "the door moved focus the reader had deliberately put down").toBe(document.body);
  });
});

/* ── the hook's contract, on the two shapes jsdom cannot lay out ────────────── */

/** A control that is REPLACED when `folded` flips (the queue's View disclosure) and states its successor. */
function Fold(): ReactElement {
  const [folded, setFolded] = useState(true);
  useReleaseFocusOnLayoutChange(folded);
  return (
    <div>
      {folded ? (
        <button type="button" className="fold-view" data-focus-successor="[id='fold-controls']" onClick={() => setFolded(false)}>
          View
        </button>
      ) : null}
      <div id="fold-controls" role="group" aria-label="Controls" hidden={folded}>
        <select aria-label="Group">
          <option>a</option>
        </select>
      </div>
    </div>
  );
}

/** A region hidden by the layout while a control inside it holds focus (the stage below 768 px). */
function Hide(): ReactElement {
  const [shown, setShown] = useState(true);
  const toggle = useRef<HTMLButtonElement | null>(null);
  useReleaseFocusOnLayoutChange(shown);
  return (
    <div>
      <button type="button" ref={toggle} className="show-toggle" onClick={() => setShown((s) => !s)}>
        Show
      </button>
      <main id="h-stage" tabIndex={-1} aria-label="Fabric" data-focus-successor=".show-toggle" style={shown ? undefined : { display: "none" }}>
        <button type="button" className="legend">
          Legend
        </button>
      </main>
    </div>
  );
}

describe("useReleaseFocusOnLayoutChange: the fourth door's contract", () => {
  it("a control replaced by a layout change hands focus to the successor it states (the View fold)", async () => {
    mountNode(<Fold />);
    await settle();
    const view = focusOn(document.querySelector<HTMLElement>(".fold-view"), "the View button");
    act(() => {
      view.click();
    });
    await settle();
    expect(document.querySelector(".fold-view"), "precondition: the View button unmounted").toBeNull();
    expect(active()?.getAttribute("aria-label"), `focus did not reach the controls it stood for (${where()})`).toBe("Group");
  });

  it("a control whose region stops being rendered (display: none) hands focus to the region's stated successor", async () => {
    mountNode(<Hide />);
    await settle();
    focusOn(document.querySelector<HTMLElement>(".legend"), "the Legend button");
    /* The layout decision arrives from outside the control (a resize); focus is still on Legend. */
    const toggle = document.querySelector<HTMLElement>(".show-toggle")!;
    const legend = document.querySelector<HTMLElement>(".legend")!;
    act(() => {
      /* Click without moving focus: the reader's focus stays on Legend, as in a resize. */
      toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    expect(legend.isConnected, "precondition: Legend is still in the document, only unrendered").toBe(true);
    expect(active(), `focus stayed on the unrendered Legend (${where()})`).toBe(toggle);
  });
});
