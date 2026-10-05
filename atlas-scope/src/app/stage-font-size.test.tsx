/**
 * stage-font-size.test.tsx — acceptance F4(c) at every browser default font size (re-grade 2).
 *
 * THE CRITERION is written in CSS pixels: at 768 px and wider the 3-D stage is the main view and
 * three.js is fetched on every load; below 768 px the stage starts collapsed and three.js is never
 * fetched until the reader presses "Show the 3-D fabric".
 *
 * THE DEFECT (independent refuter, re-grade 2, headed Chromium with a real profile Preferences file
 * and headless Chromium with CDP `Page.setFontSizes`). The stage default was keyed on the layout
 * ladder's `(min-width: 48rem)`, and a media query's rem is the browser's default font size — a
 * reader setting, not a constant 16 px:
 *   - "Small" (12 px), 700 px wide: `(min-width: 48rem)` is 576 px, so the frame seeded the fabric
 *     ON, three.js was fetched (at 1930 ms) and no "Show the 3-D fabric" button was offered;
 *   - "Large" (20 px), 900 px wide: 48rem is 960 px, so the fabric started OFF and three.js was
 *     never fetched on a load the criterion says always fetches it.
 *
 * WHAT IS PINNED. Rendered on the real App at every width x font of the refuter's grid (and the
 * boundary on each side), with `matchMedia` answered as a browser answers it at that font size
 * (`src/test-support/media-at.ts`): the frame's fabric attribute, whether anything rendered the
 * renderer, and which fabric control is offered — all three a function of CSS-pixel width alone.
 * `React.lazy` calls its factory exactly when the component first renders, so "the stand-in never
 * rendered after the waits" is "nothing asked for the renderer".
 */
import { StrictMode, act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useInvestigation } from "../core/store";
import { installMatchMediaAt, mediaListMatchesAt } from "../test-support/media-at";
import { actAsync } from "../test-support/act-turns";

vi.mock("../fabric3d/Fabric3D", () => ({ default: () => <div data-testid="fabric-mounted" />, Fabric3D: () => <div /> }));

import { App } from "./App";
import { frameGate } from "./surfaces";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
const flush = async (): Promise<void> => {
  for (let i = 0; i < 4; i += 1) {
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
};

beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
  });
});
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

const buttonNamed = (c: HTMLElement, name: string): HTMLButtonElement | undefined =>
  [...c.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim() === name);

/** The refuter's grid, and the boundary on each side of 768 px, at Chrome's Small/Medium/Large. */
const WIDTHS = [700, 767, 767.99, 768, 900] as const;
const FONTS = [12, 16, 20] as const;

describe("F4(c): the gate decision, as a pure function of the media answers", () => {
  /* `frameGate` is what App and useLadder decide from; here every query it asks is answered by
     `media-at.ts` (an evaluator written independently of breakpoint-ladder.test.ts's). */
  const at = (width: number, font: number) => frameGate((q) => mediaListMatchesAt(q, width, font));
  for (const font of FONTS) {
    for (const width of [700, 767, 768, 900] as const) {
      const wide = width >= 768;
      it(`${width} px at a ${font} px default font: stage ${wide ? "ON" : "collapsed behind its toggle"}`, () => {
        const g = at(width, font);
        expect(g.fabricDefault, "the stage starts on, so the renderer is fetched on load").toBe(wide);
        if (!wide) expect(g.stacked && g.fabricToggle, "a collapsed stage must be in the layout that offers its toggle").toBe(true);
        expect(g.fabricToggle).toBe(g.stacked);
      });
    }
  }

  it("keeps the LAYOUT on the reader's text size: the refuter's two cases each land in the stacked layout, the stage set by CSS pixels", () => {
    expect(at(900, 20)).toEqual({ stacked: true, singleColumn: false, drawer: false, fabricDefault: true, fabricToggle: true });
    expect(at(700, 12)).toEqual({ stacked: true, singleColumn: false, drawer: false, fabricDefault: false, fabricToggle: true });
    /* ...and the rem ladder still moves with text size where the stage does not: 1280 px is the
       reference layout at 16 px, the drawer at 20 px, single-column at 24 px. */
    expect(at(1280, 16)).toMatchObject({ stacked: false, singleColumn: false, drawer: false, fabricDefault: true });
    expect(at(1280, 20)).toMatchObject({ drawer: true, fabricDefault: true });
    expect(at(1280, 24)).toMatchObject({ singleColumn: true, fabricDefault: true });
  });
});

describe("F4(c): the stage default and the renderer fetch follow CSS pixels at every default font size", () => {
  for (const font of FONTS) {
    for (const width of WIDTHS) {
      const wide = width >= 768;
      it(`${width} px at a ${font} px default font: ${wide ? "the fabric is on and the renderer is asked for" : "collapsed, renderer withheld, \"Show the 3-D fabric\" offered"}`, async () => {
        const media = installMatchMediaAt(width, font);
        try {
          const c = mount(
            <StrictMode>
              <App />
            </StrictMode>,
          );
          await flush();
          expect(c.querySelector(".app")?.getAttribute("data-fabric3d"), "the frame's fabric state").toBe(wide ? "on" : "off");
          expect(c.querySelector('[data-testid="fabric-mounted"]') !== null, "something rendered the 3-D renderer").toBe(wide);
          expect(buttonNamed(c, "Show the 3-D fabric") !== undefined, '"Show the 3-D fabric" is offered').toBe(!wide);
          if (!wide) {
            /* The reader's one way in still works at this font size. */
            act(() => buttonNamed(c, "Show the 3-D fabric")!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
            await flush();
            expect(c.querySelector('[data-testid="fabric-mounted"]'), "pressing the toggle must load the renderer").not.toBeNull();
          }
        } finally {
          media.restore();
        }
      });
    }
  }
});

describe("a large default font: the stacked layout above 768 px shows the stage, and a wider layout never strands it hidden", () => {
  it('900 px at 20 px offers "Hide the 3-D fabric"; hidden there and widened to the drawer layout, the stage is shown again', async () => {
    /* At a 20 px default 900 px is 45rem — the stacked layout (the text needs it) — and >= 768 CSS px,
       so the stage starts ON with the toggle reading "Hide". Every wider layout shows the stage with
       no toggle at all, so a hide chosen here must not carry over and leave that layout's stage on
       its "Building the 3-D fabric" placeholder with nothing to bring it back. */
    const media = installMatchMediaAt(900, 20);
    try {
      const c = mount(<App />);
      await flush();
      expect(c.querySelector(".app")?.hasAttribute("data-pane"), "900 px at 20 px is the stacked layout").toBe(false);
      const hide = buttonNamed(c, "Hide the 3-D fabric");
      expect(hide, "the stacked layout's toggle, reading Hide because the stage is on").toBeTruthy();
      act(() => hide!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
      await flush();
      expect(c.querySelector(".app")?.getAttribute("data-fabric3d")).toBe("off");

      media.set(1300); // 65rem at 20 px: the drawer layout
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      await flush();
      expect(c.querySelector(".app")?.getAttribute("data-fabric3d"), "a layout with no toggle shows its stage").toBe("on");
      expect(buttonNamed(c, "Show the 3-D fabric")).toBeUndefined();

      media.set(900);
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      await flush();
      expect(c.querySelector(".app")?.getAttribute("data-fabric3d"), "back in the stacked layout the reader's hide stands").toBe("off");
    } finally {
      media.restore();
    }
  });
});
