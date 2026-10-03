/**
 * focus-return.unseen.test.tsx — a rung crossing never leaves focus on a control NO PART of which is on
 * screen (acceptance D3; independent verifier QH-V2-2).
 *
 * THE DEFECT. In every recorded focus-audit run, 768 -> 390 px with focus on the Inspector's "Copy the
 * citation path" left focus on that button "with no part of it on screen (clipped by div.app)", in four
 * page states. MEASURED (release build, 390x800, the status bar's "23/26 collected" -> "Open source record
 * collection_completeness / coverage_matrix"): the Inspector's header could not shrink below its content,
 * so the Inspector was 397 px wide in a 390 px stage and the button sat at x = 429..453, right of the
 * viewport, under `.app`'s `overflow-x: clip` below 768 px. A clip is not a scroll container, so the
 * frame's only answer to a crossing — `scrollIntoView` on whatever holds focus — could not bring it back,
 * and nothing checked that it had. The button was still rendered and still connected, so the fourth door
 * (which acts on an element the layout TOOK AWAY) did not see it either.
 *
 * THE RULE UNDER TEST, owned by focus-return.ts (`releaseFocusLeftUnseen`), for EVERY focused element,
 * not this button: after a crossing has settled and the frame has scrolled focus into view, an element
 * that still has no visible part — its box intersected with the viewport and with every ancestor that
 * clips it is empty — hands focus to the nearest place the reader CAN see: the named region around it
 * (its labelling heading, else the region), walking outward, each accepted only if it is seen once
 * focused; then the caller's fallbacks; and if nothing is seen, focus stays where it was (never <body>).
 * An element with no box to measure (a DOM nothing lays out) is unknown, not unseen: nothing moves.
 *
 * jsdom lays nothing out, so geometry is STATED here per element (every other element measures 0x0,
 * "unknown"). The layout half — the Inspector's header now fits a 390 px stage — is proved in a real
 * browser by `review/audit-d3-focus.mjs --crossings --vp=390` (each of the four page states).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { openInspector } from "../panels/Inspector";
import { flushTurns } from "../test-support/act-turns";
import { App } from "./App";
import { keepFocusSeen, releaseFocusLeftUnseen } from "./focus-return";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ── geometry, stated ────────────────────────────────────────────────────── */

type Box = { x: number; y: number; w: number; h: number };
const boxes = new Map<Element, Box>();
let viewport = { w: 390, h: 800 };
const realRect = Element.prototype.getBoundingClientRect;
const realClientWidth = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
const realClientHeight = Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight");

function stateGeometry(): void {
  Element.prototype.getBoundingClientRect = function (this: Element): DOMRect {
    const b = boxes.get(this) ?? { x: 0, y: 0, w: 0, h: 0 };
    return { left: b.x, top: b.y, right: b.x + b.w, bottom: b.y + b.h, width: b.w, height: b.h, x: b.x, y: b.y, toJSON: () => ({}) } as DOMRect;
  };
  Object.defineProperty(Element.prototype, "clientWidth", {
    configurable: true,
    get(this: Element) {
      if (this === document.documentElement) return viewport.w;
      return boxes.get(this)?.w ?? 0;
    },
  });
  Object.defineProperty(Element.prototype, "clientHeight", {
    configurable: true,
    get(this: Element) {
      if (this === document.documentElement) return viewport.h;
      return boxes.get(this)?.h ?? 0;
    },
  });
}
function restoreGeometry(): void {
  Element.prototype.getBoundingClientRect = realRect;
  if (realClientWidth) Object.defineProperty(Element.prototype, "clientWidth", realClientWidth);
  if (realClientHeight) Object.defineProperty(Element.prototype, "clientHeight", realClientHeight);
  boxes.clear();
}
const place = (el: Element | null, b: Box): Element => {
  expect(el, "precondition: the element to place is rendered").not.toBeNull();
  boxes.set(el!, b);
  return el!;
};

afterEach(() => {
  restoreGeometry();
  document.body.innerHTML = "";
  viewport = { w: 390, h: 800 };
});

/* ── the owner's decision, in isolation ───────────────────────────────────── */

describe("releaseFocusLeftUnseen: focus with no visible part goes to the nearest place the reader can see", () => {
  function mount(): { control: HTMLButtonElement; region: HTMLElement; heading: HTMLElement; outer: HTMLElement; clip: HTMLElement } {
    document.body.innerHTML = `
      <main id="outer" aria-label="Fabric">
        <div id="clip" style="overflow-x: clip">
          <section id="region" aria-labelledby="region-title">
            <h2 id="region-title">Inspector</h2>
            <header><button id="control">Copy</button></header>
          </section>
        </div>
      </main>`;
    stateGeometry();
    /* The clipping box spans the viewport unless a case narrows it: a clip is measured like any other box. */
    place(document.getElementById("clip"), { x: 0, y: 0, w: 390, h: 800 });
    return {
      control: document.getElementById("control") as HTMLButtonElement,
      region: document.getElementById("region")!,
      heading: document.getElementById("region-title")!,
      outer: document.getElementById("outer")!,
      clip: document.getElementById("clip")!,
    };
  }

  it("a control right of a 390 px viewport (the measured Inspector button): focus goes to its region's heading", () => {
    const { control, heading, region } = mount();
    place(control, { x: 429, y: 182, w: 24, h: 24 });
    place(region, { x: 0, y: 152, w: 397, h: 316 });
    place(heading, { x: 12, y: 180, w: 70, h: 24 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBe(heading);
    expect(document.activeElement).toBe(heading);
  });

  it("clipped by an ANCESTOR while inside the viewport: the same (the clip is measured, not only the viewport)", () => {
    const { control, heading, clip } = mount();
    place(clip, { x: 0, y: 0, w: 200, h: 800 });
    place(control, { x: 250, y: 182, w: 24, h: 24 });
    place(heading, { x: 12, y: 180, w: 70, h: 24 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBe(heading);
  });

  it("a heading that is itself unseen is passed over: the region, then the next region out", () => {
    const { control, heading, region, outer } = mount();
    place(control, { x: 429, y: 182, w: 24, h: 24 });
    place(heading, { x: 400, y: 180, w: 70, h: 24 });
    place(region, { x: 395, y: 152, w: 397, h: 316 });
    place(outer, { x: 0, y: 100, w: 390, h: 400 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBe(outer);
    expect(document.activeElement).toBe(outer);
  });

  it("nothing around it is seen: the caller's fallback, landed on its first tab stop", () => {
    const { control } = mount();
    const aside = document.createElement("div");
    aside.innerHTML = `<button id="fb">Query</button>`;
    document.body.append(aside);
    const fb = document.getElementById("fb")!;
    place(control, { x: 429, y: 182, w: 24, h: 24 });
    place(fb, { x: 10, y: 10, w: 80, h: 28 });
    control.focus();
    expect(releaseFocusLeftUnseen([aside])).toBe(fb);
  });

  it("nothing anywhere is seen: focus stays exactly where it was — never <body>", () => {
    const { control, heading, region, outer } = mount();
    place(control, { x: 429, y: 182, w: 24, h: 24 });
    place(heading, { x: 500, y: 180, w: 70, h: 24 });
    place(region, { x: 500, y: 152, w: 397, h: 316 });
    place(outer, { x: 0, y: 900, w: 390, h: 400 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement).toBe(control);
    expect(region.hasAttribute("tabindex")).toBe(false);
  });

  it("a control with ANY visible part keeps focus (a partly clipped control is the reveal's, not this door's)", () => {
    const { control } = mount();
    place(control, { x: 380, y: 182, w: 24, h: 24 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement).toBe(control);
  });

  it("a control with NO box to measure is unknown, not unseen: nothing moves", () => {
    const { control, heading } = mount();
    place(heading, { x: 12, y: 180, w: 70, h: 24 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement).toBe(control);
  });

  it("a fixed box escapes a clipping ancestor that is not its containing block", () => {
    const { control, clip, heading } = mount();
    control.style.position = "fixed";
    place(clip, { x: 0, y: 0, w: 200, h: 800 });
    place(control, { x: 250, y: 182, w: 24, h: 24 });
    /* A SEEN place to go (independent verifier V1-2): without it, a broken escape would also end with focus left on
       the control — nothing seen, restored — and this case would pass whether or not the escape works. */
    place(heading, { x: 12, y: 180, w: 70, h: 24 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement).toBe(control);
  });
});

/* ── judged where it comes to rest ────────────────────────────────────────── */

describe("an element that is MOVING is judged where it comes to rest, not mid-flight", () => {
  /* MEASURED (release build, draws suspended, R-D3 render check and probe-skip3): a crossing's 400 ms look at focus
     fired 80 ms after the reader focused the skip link, which slides in from above the viewport on :focus-visible
     (`transition: top`, shell.css). At that instant it was still at top = -56, "unseen", and focus was moved to the
     stage — away from a control that was on its way into view. */
  function mount(): { control: HTMLButtonElement; heading: HTMLElement } {
    document.body.innerHTML = `
      <section id="region" aria-labelledby="region-title">
        <h2 id="region-title">Fabric</h2>
        <a id="control" href="#stage">Skip to the fabric</a>
      </section>`;
    stateGeometry();
    return { control: document.getElementById("control") as HTMLButtonElement, heading: document.getElementById("region-title")! };
  }
  /** A running, finite transition on `el` that finishes when `finish` is called. */
  function sliding(el: Element): { finish: () => Promise<void> } {
    let done!: () => void;
    const finished = new Promise<void>((r) => (done = r));
    const anim = { playState: "running", finished, effect: { getComputedTiming: () => ({ endTime: 120 }) } };
    (el as unknown as { getAnimations: () => unknown[] }).getAnimations = () => (anim.playState === "running" ? [anim] : []);
    return {
      finish: async () => {
        anim.playState = "finished";
        done();
        await finished;
        await Promise.resolve();
        await Promise.resolve();
      },
    };
  }

  it("mid-slide above the viewport, then at rest on screen: focus stays on it", async () => {
    const { control, heading } = mount();
    place(control, { x: 8, y: -56, w: 118, h: 36 });
    place(heading, { x: 12, y: 180, w: 70, h: 24 });
    const slide = sliding(control);
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement, "focus was moved while the control was still sliding into view").toBe(control);
    place(control, { x: 8, y: 8, w: 118, h: 36 });
    await slide.finish();
    expect(document.activeElement).toBe(control);
  });

  it("at rest and still wholly off screen: then, and only then, focus moves", async () => {
    const { control, heading } = mount();
    place(control, { x: 8, y: -56, w: 118, h: 36 });
    place(heading, { x: 12, y: 180, w: 70, h: 24 });
    const slide = sliding(control);
    control.focus();
    expect(keepFocusSeen()).toBeNull();
    expect(document.activeElement).toBe(control);
    await slide.finish();
    expect(document.activeElement).toBe(heading);
  });
});

/* ── a scroll first, then the move (keepFocusSeen) ─────────────────────────── */

describe("keepFocusSeen: an unseen focused element is scrolled into view first, and moved only if that cannot reveal it", () => {
  function mount(): { control: HTMLButtonElement; heading: HTMLElement } {
    document.body.innerHTML = `
      <section id="region" aria-labelledby="region-title">
        <h2 id="region-title">Queue</h2>
        <div id="scroller" style="overflow-y: auto"><button id="control">Row 40</button></div>
      </section>`;
    stateGeometry();
    return { control: document.getElementById("control") as HTMLButtonElement, heading: document.getElementById("region-title")! };
  }

  it("a scroller CAN reveal it: it is scrolled into view and keeps focus", () => {
    const { control, heading } = mount();
    place(document.getElementById("scroller"), { x: 0, y: 100, w: 390, h: 300 });
    place(control, { x: 10, y: 900, w: 120, h: 28 });
    place(heading, { x: 12, y: 60, w: 70, h: 24 });
    let scrolled = 0;
    control.scrollIntoView = () => {
      scrolled += 1;
      place(control, { x: 10, y: 200, w: 120, h: 28 });
    };
    control.focus();
    expect(keepFocusSeen()).toBeNull();
    expect(scrolled).toBe(1);
    expect(document.activeElement).toBe(control);
  });

  it("no scroll can reveal it: focus goes to the nearest seen place", () => {
    const { control, heading } = mount();
    place(document.getElementById("scroller"), { x: 0, y: 100, w: 390, h: 300 });
    place(control, { x: 429, y: 200, w: 24, h: 24 });
    place(heading, { x: 12, y: 60, w: 70, h: 24 });
    control.scrollIntoView = () => {};
    control.focus();
    expect(keepFocusSeen()).toBe(heading);
  });

  it("a seen control is not scrolled at all (nothing moves under the reader)", () => {
    const { control } = mount();
    place(document.getElementById("scroller"), { x: 0, y: 100, w: 390, h: 300 });
    place(control, { x: 10, y: 200, w: 120, h: 28 });
    let scrolled = 0;
    control.scrollIntoView = () => {
      scrolled += 1;
    };
    control.focus();
    expect(keepFocusSeen()).toBeNull();
    expect(scrolled).toBe(0);
  });
});

/* ── the frame runs it on every rung crossing ─────────────────────────────── */

const mounted: { root: Root; container: HTMLElement }[] = [];
let width = 768;
const realMatchMedia = window.matchMedia;
function answerMedia(): void {
  window.matchMedia = ((q: string) => {
    let matches = true;
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)rem\)/g)) {
      const bound = Number.parseFloat(m[2] as string) * 16;
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

describe("the frame: a crossing that leaves the focused control wholly off screen hands focus on", () => {
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
    window.matchMedia = realMatchMedia;
    window.history.replaceState(null, "", "/");
    act(() => {
      useInvestigation.setState(useInvestigation.getInitialState(), true);
    });
  });

  it("768 -> 390 with focus on the Inspector's 'Copy the citation path', laid out right of the viewport: focus lands in the Inspector, on screen", async () => {
    width = 768;
    answerMedia();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => {
      root.render(<App />);
    });
    mounted.push({ root, container });
    await flushTurns(20, 8);
    act(() => {
      openInspector(fabric.findings[0]!.cite);
    });
    await flushTurns(20, 8);
    const copy = document.querySelector<HTMLElement>('#inspector button[aria-label="Copy the citation path"]');
    const inspector = document.getElementById("inspector");
    expect(copy, "precondition: the Inspector shows a citation and its copy control").not.toBeNull();
    act(() => {
      copy!.focus();
    });
    expect(document.activeElement).toBe(copy);

    /* The layout the release build measured at 390 px: the Inspector on screen, the button right of it. */
    stateGeometry();
    viewport = { w: 390, h: 800 };
    place(inspector, { x: 0, y: 152, w: 390, h: 316 });
    place(copy, { x: 429, y: 182, w: 24, h: 24 });

    width = 390;
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    /* The frame looks again once the new layout has settled (App.tsx: two frames, and 400 ms). */
    await flushTurns(450, 1);
    await flushTurns(20, 8);
    const a = document.activeElement;
    expect(a, "focus stayed on a control no part of which is on screen").not.toBe(copy);
    expect(a).not.toBe(document.body);
    expect(a).toBe(inspector);
  });

  it("a resize WITHIN one rung (700 -> 390, both stacked) that leaves the control wholly off screen hands focus on too (independent verifier V1-4)", async () => {
    width = 700;
    answerMedia();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => {
      root.render(<App />);
    });
    mounted.push({ root, container });
    await flushTurns(20, 8);
    act(() => {
      openInspector(fabric.findings[0]!.cite);
    });
    await flushTurns(20, 8);
    const copy = document.querySelector<HTMLElement>('#inspector button[aria-label="Copy the citation path"]');
    const inspector = document.getElementById("inspector");
    expect(copy, "precondition: the Inspector shows a citation and its copy control").not.toBeNull();
    act(() => {
      copy!.focus();
    });

    /* A layout in which, at 390 px, the button is right of the viewport (the verifier's injected offset). */
    stateGeometry();
    viewport = { w: 390, h: 800 };
    place(inspector, { x: 0, y: 152, w: 390, h: 316 });
    place(copy, { x: 782, y: 182, w: 28, h: 24 });

    width = 390;
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    await flushTurns(450, 1);
    await flushTurns(20, 8);
    const a = document.activeElement;
    expect(a, "a resize inside one rung left focus on a control no part of which is on screen").not.toBe(copy);
    expect(a).toBe(inspector);
  });
});

/* ── the crossing path, pinned ON ITS OWN (independent verifier V2-2) ──────────
   The frame has two callers of the owner's "focus is seen" step: the rung crossing's settle (App.tsx, the rung
   effect: `releaseFocusLeftUnseen` 400 ms after a crossing) and the resize listener's `keepFocusSeen`. The verifier
   deleted the first and every test stayed green, because each test crossed a rung BY a resize, which also fires the
   listener at the same 400 ms. They are not one case: the ladder is in rem, so a rung is crossed WITHOUT any resize
   when the reader's default font size changes (the media queries re-evaluate; `useRungIndex` listens to them), and
   then the crossing's settle is the only owner that runs. This case crosses by the media queries alone. */
describe("a crossing made by the media queries alone (no resize event) still hands unseen focus on", () => {
  const listeners = new Set<() => void>();
  function answerMediaLive(): void {
    window.matchMedia = ((q: string) => {
      let matches = true;
      for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)rem\)/g)) {
        const bound = Number.parseFloat(m[2] as string) * 16;
        matches &&= m[1] === "min" ? width >= bound : width <= bound;
      }
      if (/prefers-reduced-motion/.test(q)) matches = false;
      return {
        matches,
        media: q,
        onchange: null,
        addEventListener: (_t: string, cb: () => void) => void listeners.add(cb),
        removeEventListener: (_t: string, cb: () => void) => void listeners.delete(cb),
        addListener: (cb: () => void) => void listeners.add(cb),
        removeListener: (cb: () => void) => void listeners.delete(cb),
        dispatchEvent: () => false,
      } as unknown as MediaQueryList;
    }) as typeof window.matchMedia;
  }
  afterEach(() => {
    for (const m of mounted.splice(0)) {
      act(() => {
        m.root.unmount();
      });
      m.container.remove();
    }
    listeners.clear();
    window.matchMedia = realMatchMedia;
    window.history.replaceState(null, "", "/");
    act(() => {
      useInvestigation.setState(useInvestigation.getInitialState(), true);
    });
  });

  it("768 -> 390 by a font-size change: no resize fires, and focus still leaves the clipped 'Copy the citation path' for the Inspector", async () => {
    act(() => {
      useInvestigation.setState(useInvestigation.getInitialState(), true);
    });
    width = 768;
    answerMediaLive();
    let resizes = 0;
    const countResize = (): void => void (resizes += 1);
    window.addEventListener("resize", countResize);
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => {
      root.render(<App />);
    });
    mounted.push({ root, container });
    await flushTurns(20, 8);
    act(() => {
      openInspector(fabric.findings[0]!.cite);
    });
    await flushTurns(20, 8);
    const copy = document.querySelector<HTMLElement>('#inspector button[aria-label="Copy the citation path"]');
    const inspector = document.getElementById("inspector");
    expect(copy, "precondition: the Inspector shows a citation and its copy control").not.toBeNull();
    act(() => {
      copy!.focus();
    });
    expect(listeners.size, "precondition: the frame listens to the ladder's media queries").toBeGreaterThan(0);

    stateGeometry();
    viewport = { w: 390, h: 800 };
    place(inspector, { x: 0, y: 152, w: 390, h: 316 });
    place(copy, { x: 429, y: 182, w: 24, h: 24 });

    /* The media queries change — and nothing else does. */
    width = 390;
    act(() => {
      for (const cb of [...listeners]) cb();
    });
    await flushTurns(450, 1);
    await flushTurns(20, 8);
    window.removeEventListener("resize", countResize);
    expect(resizes, "precondition: the crossing came from the media queries alone").toBe(0);
    const a = document.activeElement;
    expect(a, "a crossing with no resize event left focus on a control no part of which is on screen").not.toBe(copy);
    expect(a).not.toBe(document.body);
    expect(a).toBe(inspector);
  });
});
